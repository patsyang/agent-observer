"""离线重建会话物化层（停服期间运行）。

把 observed_facts + evidence_projections 全量回放进会话物化表
（conversations / conversation_messages / conversation_hits / conversation_messages_fts）。
幂等：先清空物化层，再按 (occurred_at, fact_id) 顺序回放。

用法::

    cd backend
    python -m scripts.rebuild_conversations --db data/agent-observer.sqlite \
        [--batch-size 500] [--sleep 0.1] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.conversations.materialize import (  # noqa: E402
    FactProjection,
    apply,
    enable_turn_cache,
    rebuild_secondary_indexes,
)
from app.db.connection import connect  # noqa: E402


def _usage_for_fact(conn, fact_id: str) -> dict | None:
    row = conn.execute(
        "select units, input_tokens, output_tokens, total_tokens, cached_input_tokens, "
        "cache_write_input_tokens, reasoning_output_tokens, credit, cache_observed "
        "from usage_signals where fact_id = ? limit 1",
        (fact_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "units": row["units"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "total_tokens": row["total_tokens"],
        "cached_input_tokens": row["cached_input_tokens"],
        "cache_write_input_tokens": row["cache_write_input_tokens"],
        "reasoning_output_tokens": row["reasoning_output_tokens"],
        "credit": row["credit"],
        "cache_observed": row["cache_observed"],
    }


def _clear_materialization(conn) -> None:
    conn.execute("delete from conversation_messages_fts")
    conn.execute("delete from conversation_hits")
    conn.execute("delete from conversation_messages")
    conn.execute("delete from conversations")
    conn.commit()


def rebuild(conn, *, batch_size: int = 500, sleep_seconds: float = 0.1, dry_run: bool = False) -> dict:
    stats = {"processed": 0, "errors": 0, "conversations": 0, "last_fact_id": "", "last_occurred_at": ""}
    enable_turn_cache(True)
    if not dry_run:
        _clear_materialization(conn)
    wm_occurred, wm_fact_id = "", ""
    while True:
        batch = conn.execute(
            "select * from observed_facts "
            "where fact_type != 'collector_health' "
            "  and (occurred_at > ? or (occurred_at = ? and fact_id > ?)) "
            "order by occurred_at asc, fact_id asc limit ?",
            (wm_occurred, wm_occurred, wm_fact_id, batch_size),
        ).fetchall()
        if not batch:
            break
        for fact_row in batch:
            try:
                proj_row = conn.execute(
                    "select projection_json, raw_content from evidence_projections "
                    "where fact_id = ? order by projection_id limit 1",
                    (fact_row["fact_id"],),
                ).fetchone()
                projection = FactProjection.from_rows(conn, fact_row, proj_row)
                if fact_row["fact_type"] == "usage":
                    projection.usage = _usage_for_fact(conn, fact_row["fact_id"])
                if not dry_run:
                    apply(conn, projection, maintain_index=False)
                stats["processed"] += 1
            except Exception as exc:  # 单条失败不中断
                stats["errors"] += 1
                print(f"[error] fact_id={fact_row['fact_id']}: {exc}", file=sys.stderr)
            wm_occurred, wm_fact_id = fact_row["occurred_at"], fact_row["fact_id"]
        if not dry_run:
            conn.commit()
        stats["last_occurred_at"], stats["last_fact_id"] = wm_occurred, wm_fact_id
        print(f"  batch: processed={stats['processed']} errors={stats['errors']}")
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    if not dry_run:
        rebuild_secondary_indexes(conn)
        stats["conversations"] = conn.execute("select count(*) from conversations").fetchone()[0]
    enable_turn_cache(False)
    return stats


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="重建会话物化层")
    parser.add_argument("--db", required=True, help="SQLite DB 路径")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--sleep", type=float, default=0.1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    conn = connect(args.db)
    try:
        result = rebuild(
            conn, batch_size=args.batch_size, sleep_seconds=args.sleep, dry_run=args.dry_run
        )
        print(result)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
