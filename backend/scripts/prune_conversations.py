"""按时间裁剪会话物化层（删除 last_event_at 早于 cutoff 的会话）。

只删物化层（conversations / messages / hits / fts），不动 observed_facts 等证据源。
小批删除 + commit + sleep，让出写锁；--dry-run 只统计不删。

用法::

    cd backend
    python -m scripts.prune_conversations --db data/agent-observer.sqlite --older-than 90d [--dry-run]
    python -m scripts.prune_conversations --db data/agent-observer.sqlite --cutoff 2026-04-01T00:00:00Z
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.connection import connect  # noqa: E402


def parse_cutoff(older_than: str | None = None, cutoff: str | None = None) -> str:
    if cutoff:
        return cutoff
    if not older_than:
        raise SystemExit("需要 --older-than（如 30d/12h）或 --cutoff（ISO8601）")
    value = older_than.strip().lower()
    try:
        if value.endswith("d"):
            delta = timedelta(days=int(value[:-1]))
        elif value.endswith("h"):
            delta = timedelta(hours=int(value[:-1]))
        else:
            delta = timedelta(days=int(value))
    except ValueError:
        raise SystemExit(f"无法解析 --older-than: {older_than}")
    return (datetime.now(UTC) - delta).replace(microsecond=0).isoformat()


def _prune_batch(conn, cutoff: str, batch_size: int) -> int:
    rows = conn.execute(
        "select conversation_ref from conversations where last_event_at < ? limit ?",
        (cutoff, batch_size),
    ).fetchall()
    refs = [row["conversation_ref"] for row in rows]
    if not refs:
        return 0
    placeholders = ",".join("?" for _ in refs)
    conn.execute(f"delete from conversation_messages_fts where conversation_ref in ({placeholders})", refs)
    # conversations 删除 → messages/hits 经 on delete cascade 清除
    conn.execute(f"delete from conversations where conversation_ref in ({placeholders})", refs)
    return len(refs)


def prune(conn, *, cutoff: str, batch_size: int = 500, sleep_seconds: float = 0.1, dry_run: bool = False) -> dict:
    if dry_run:
        count = conn.execute(
            "select count(*) from conversations where last_event_at < ?", (cutoff,)
        ).fetchone()[0]
        return {"dry_run": True, "would_delete": count, "cutoff": cutoff}
    deleted_total = 0
    while True:
        deleted = _prune_batch(conn, cutoff, batch_size)
        if deleted == 0:
            break
        deleted_total += deleted
        conn.commit()
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return {"deleted": deleted_total, "cutoff": cutoff}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="裁剪会话物化层")
    parser.add_argument("--db", required=True, help="SQLite DB 路径")
    parser.add_argument("--older-than", help="相对时长，如 30d / 12h")
    parser.add_argument("--cutoff", help="ISO8601 截止时间")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--sleep", type=float, default=0.1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cutoff = parse_cutoff(args.older_than, args.cutoff)
    conn = connect(args.db)
    try:
        result = prune(
            conn, cutoff=cutoff, batch_size=args.batch_size,
            sleep_seconds=args.sleep, dry_run=args.dry_run,
        )
        print(result)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
