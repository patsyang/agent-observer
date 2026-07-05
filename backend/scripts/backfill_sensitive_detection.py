"""离线回填脚本：用统一 detector 扫描历史 content/tool fact，补齐 sensitive_matches + risk_signal。

用法：
    cd backend
    python -m scripts.backfill_sensitive_detection --db data/agent-observer.sqlite [--batch-size 100] [--sleep 0.5] [--sample 100]

设计要点（对齐 plan [F4][F5][F6]）：
- [F4] watermark 进 DB 表 backfill_watermark(created_at, fact_id)，与业务 UPDATE 同事务；
      查询用 `created_at > ? OR (created_at = ? AND fact_id > ?)`，避免秒级 created_at 漏 fact。
- [F5] 小批 100 条/事务，批间 time.sleep(0.5) 让出写锁；WAL 下与在线 ingest 并发安全。
- [F6] detector 内部吞异常；脚本层额外 try/except 单条 fact，失败只记录不中断。
- 幂等：insert or ignore + UPDATE 已有 risk_signal 的 object_type，可重跑。
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

# 让脚本独立于运行时 PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.connection import connect  # noqa: E402
from app.sensitive_detector import detect_for_fact, object_type_from_matches  # noqa: E402

BATCH_DEFAULT = 100
SLEEP_DEFAULT = 0.5
SAMPLE_DEFAULT = 100

CREATE_WATERMARK_SQL = """
create table if not exists backfill_watermark (
  id integer primary key check (id = 1),
  created_at text not null,
  fact_id text not null,
  updated_at text not null
);
"""


def _ensure_watermark_table(conn: sqlite3.Connection) -> None:
    conn.executescript(CREATE_WATERMARK_SQL)
    conn.execute(
        "insert or ignore into backfill_watermark (id, created_at, fact_id, updated_at) values (1, '', '', '')"
    )
    conn.commit()


def _read_watermark(conn: sqlite3.Connection) -> tuple[str, str]:
    row = conn.execute(
        "select created_at, fact_id from backfill_watermark where id = 1"
    ).fetchone()
    return (row["created_at"] if row else "", row["fact_id"] if row else "")


def _advance_watermark(
    conn: sqlite3.Connection, created_at: str, fact_id: str, now: str
) -> None:
    conn.execute(
        "update backfill_watermark set created_at = ?, fact_id = ?, updated_at = ? where id = 1",
        (created_at, fact_id, now),
    )


def _fetch_batch(
    conn: sqlite3.Connection, wm_created_at: str, wm_fact_id: str, batch_size: int
) -> list[sqlite3.Row]:
    """[F4] 按 (created_at, fact_id) 水位线分批，避免秒级 created_at 漏 fact。"""
    return conn.execute(
        """
        select fact_id, fact_type, category, created_at
        from observed_facts
        where fact_type in ('content', 'tool')
          and (
            created_at > ?
            or (created_at = ? and fact_id > ?)
          )
        order by created_at asc, fact_id asc
        limit ?
        """,
        (wm_created_at, wm_created_at, wm_fact_id, batch_size),
    ).fetchall()


def _load_projection(
    conn: sqlite3.Connection, fact_id: str
) -> tuple[dict | None, str | None]:
    """返回 (projection_json dict, raw_content)。取主 projection（最早一条）。"""
    row = conn.execute(
        "select projection_json, raw_content from evidence_projections "
        "where fact_id = ? order by projection_id limit 1",
        (fact_id,),
    ).fetchone()
    if row is None:
        return None, None
    try:
        proj = json.loads(row["projection_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        proj = {}
    return proj, row["raw_content"]


def _stamp_projection(proj: dict, matches: list[dict], *, recompute: bool = False) -> dict:
    """把 sensitive_matches 注入 projection dict。

    增量模式（默认）：不覆盖已有非空值。
    重算模式（recompute=True）：用新检测结果整体覆盖；无命中则清除旧字段，
    保证旧误报（装饰器/换行 n 前缀/占位域）被彻底清掉。
    """
    if recompute:
        if matches:
            proj["sensitive_matches"] = matches
            proj["sensitivity_confidence"] = "high"
            proj["sensitive_categories"] = sorted({m["category"] for m in matches})
        else:
            proj.pop("sensitive_matches", None)
            proj.pop("sensitivity_confidence", None)
            proj.pop("sensitive_categories", None)
        return proj
    if not proj.get("sensitive_matches"):
        proj["sensitive_matches"] = matches
        proj["sensitivity_confidence"] = "high"
        proj["sensitive_categories"] = sorted({m["category"] for m in matches})
    return proj


def _reconcile_sensitive_risk(
    conn: sqlite3.Connection, fact_id: str, object_type: str | None
) -> None:
    """重算模式专用：删除该 fact 旧的 sensitive risk_signal，有新命中再插入。"""
    conn.execute(
        "delete from risk_signals where signal_id = ?",
        (f"risk:sensitive:{fact_id}",),
    )
    if object_type:
        conn.execute(
            "insert into risk_signals (signal_id, fact_id, risk_type, severity, object_type) "
            "values (?, ?, 'sensitive_content_exposure', 'high', ?) "
            "on conflict(signal_id) do update set object_type=excluded.object_type, severity='high'",
            (f"risk:sensitive:{fact_id}", fact_id, object_type),
        )


def _update_projection_json(
    conn: sqlite3.Connection, fact_id: str, projection_id: str, proj_json: str
) -> None:
    conn.execute(
        "update evidence_projections set projection_json = ? where projection_id = ?",
        (proj_json, projection_id),
    )


def _upsert_risk_signal(
    conn: sqlite3.Connection, fact_id: str, object_type: str
) -> None:
    """UPSERT sensitive risk_signal。signal_id=risk:sensitive:{fact_id}，detector 唯一写者。

    新 fact：insert or ignore。
    已有：UPDATE object_type（[F3] duplicate 时 object_type 重算）。
    """
    conn.execute(
        "insert into risk_signals (signal_id, fact_id, risk_type, severity, object_type) "
        "values (?, ?, 'sensitive_content_exposure', 'high', ?) "
        "on conflict(signal_id) do update set object_type=excluded.object_type, severity='high'",
        (f"risk:sensitive:{fact_id}", fact_id, object_type),
    )


def _process_fact(
    conn: sqlite3.Connection, fact_id: str, *, dry_run: bool = False, recompute: bool = False
) -> dict | None:
    """对单条 fact 跑 detector，命中则更新 projection + risk_signal（dry_run 只检测不写库）。

    recompute=True 时，无命中也会清除该 fact 旧的 sensitive_matches 与 risk_signal，
    用于把旧检测器的误报从库里彻底清掉。
    """
    proj_row = conn.execute(
        "select projection_id, projection_json, raw_content from evidence_projections "
        "where fact_id = ? order by projection_id limit 1",
        (fact_id,),
    ).fetchone()
    if proj_row is None:
        return None
    try:
        proj = json.loads(proj_row["projection_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        proj = {}
    raw_content = proj_row["raw_content"] or ""
    proj_json_text = json.dumps(proj, ensure_ascii=False, sort_keys=True, default=str)
    # 与 ingest 端 _detect_fact_sensitive 一致：优先只扫 raw_content（完整 record，
    # 是 projection 的超集）；缺失才扫 projection_json，避免同一 PII 被重复命中。
    if raw_content:
        high = detect_for_fact(None, raw_content, source="backfill")
    else:
        high = detect_for_fact(proj_json_text, None, source="backfill")
    object_type = object_type_from_matches(high) if high else None
    had_old = bool(proj.get("sensitive_matches"))
    # 增量模式且无命中：无事可做。重算模式：即便无命中也要清除旧误报。
    if not high and not (recompute and had_old):
        return None
    if not dry_run:
        _stamp_projection(proj, high, recompute=recompute)
        _update_projection_json(conn, fact_id, proj_row["projection_id"],
                                json.dumps(proj, ensure_ascii=False, sort_keys=True, default=str))
        if recompute:
            _reconcile_sensitive_risk(conn, fact_id, object_type)
        elif object_type:
            _upsert_risk_signal(conn, fact_id, object_type)
    return {
        "fact_id": fact_id,
        "object_type": object_type,
        "matches": high,
        "preview": (raw_content[:80] + "...") if len(raw_content) > 80 else raw_content,
    }


def backfill(
    conn: sqlite3.Connection,
    *,
    batch_size: int = BATCH_DEFAULT,
    sleep_seconds: float = SLEEP_DEFAULT,
    sample_size: int = SAMPLE_DEFAULT,
    dry_run: bool = False,
    recompute: bool = False,
) -> dict:
    """执行回填，返回统计摘要 + 抽样命中。

    recompute=True：重置水位线全量重扫，用新检测结果整体覆盖 projection 的
    sensitive_matches 并删除/重建 sensitive risk_signal（清除旧误报）；结束后
    入队一次全局信号重建，让 behavior_signals 与新 risk_signal 对齐。
    """
    _ensure_watermark_table(conn)
    if recompute and not dry_run:
        _advance_watermark(conn, "", "", _now_iso())
        conn.commit()
    stats: dict = {
        "scanned": 0,
        "hit_facts": 0,
        "cleared_facts": 0,
        "by_object_type": {},
        "by_category": {},
        "samples": [],
        "last_fact_id": "",
        "last_created_at": "",
        "errors": 0,
    }
    wm_created_at, wm_fact_id = (_read_watermark(conn) if not recompute else ("", ""))
    total_batches = 0
    while True:
        batch = _fetch_batch(conn, wm_created_at, wm_fact_id, batch_size)
        if not batch:
            break
        batch_hits: list[dict] = []
        for row in batch:
            stats["scanned"] += 1
            fact_id = row["fact_id"]
            created_at = row["created_at"]
            try:
                hit = _process_fact(conn, fact_id, dry_run=dry_run, recompute=recompute)
                if hit:
                    if hit["matches"]:
                        stats["hit_facts"] += 1
                        ot = hit["object_type"]
                        stats["by_object_type"][ot] = stats["by_object_type"].get(ot, 0) + 1
                        for m in hit["matches"]:
                            cat = m["category"]
                            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
                        batch_hits.append(hit)
                    else:
                        stats["cleared_facts"] += 1
            except Exception as exc:  # [F6] 单条失败不中断
                stats["errors"] += 1
                print(f"  [error] fact_id={fact_id}: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
            wm_created_at = created_at
            wm_fact_id = fact_id
        if not dry_run:
            now = _now_iso()
            _advance_watermark(conn, wm_created_at, wm_fact_id, now)
            conn.commit()
        # 抽样：随机选命中，最多 sample_size 条
        if batch_hits and len(stats["samples"]) < sample_size:
            remaining = sample_size - len(stats["samples"])
            stats["samples"].extend(batch_hits[:remaining])
        total_batches += 1
        print(f"  batch {total_batches}: scanned={stats['scanned']} "
              f"hits={stats['hit_facts']} cleared={stats['cleared_facts']} "
              f"errors={stats['errors']}")
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    stats["last_fact_id"] = wm_fact_id
    stats["last_created_at"] = wm_created_at
    if recompute and not dry_run and (stats["hit_facts"] or stats["cleared_facts"]):
        try:
            from app.processing.jobs import enqueue_global_signal_rebuild
            job = enqueue_global_signal_rebuild(conn, reason="sensitive_recompute")
            conn.commit()
            stats["rebuild_job"] = job.get("job_id")
            print(f"  enqueued signal rebuild: {job.get('job_id')}")
        except Exception as exc:
            stats["rebuild_error"] = str(exc)
            print(f"  [warn] failed to enqueue signal rebuild: {exc}", file=sys.stderr)
    return stats


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill sensitive detection for historical facts")
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument("--batch-size", type=int, default=BATCH_DEFAULT)
    parser.add_argument("--sleep", type=float, default=SLEEP_DEFAULT)
    parser.add_argument("--sample", type=int, default=SAMPLE_DEFAULT)
    parser.add_argument("--dry-run", action="store_true", help="只扫描统计，不写库")
    parser.add_argument("--recompute", action="store_true",
                        help="重算模式：重置水位线全量重扫，覆盖 projection sensitive_matches "
                             "并删除/重建 sensitive risk_signal，清除旧误报；结束后入队信号重建")
    args = parser.parse_args()

    conn = connect(args.db)
    print(f"Backfilling {args.db} (batch={args.batch_size}, sleep={args.sleep}s, "
          f"dry_run={args.dry_run}, recompute={args.recompute})...")
    stats = backfill(
        conn,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep,
        sample_size=args.sample,
        dry_run=args.dry_run,
        recompute=args.recompute,
    )
    conn.close()
    print("\n=== Backfill summary ===")
    print(f"scanned:         {stats['scanned']}")
    print(f"hit_facts:       {stats['hit_facts']}")
    print(f"cleared_facts:   {stats['cleared_facts']}")
    print(f"errors:          {stats['errors']}")
    print(f"by_object_type:  {stats['by_object_type']}")
    print(f"by_category:     {stats['by_category']}")
    if stats.get("rebuild_job"):
        print(f"rebuild_job:     {stats['rebuild_job']}")
    if stats.get("rebuild_error"):
        print(f"rebuild_error:   {stats['rebuild_error']}")
    print(f"last_fact_id:    {stats['last_fact_id']}")
    print(f"last_created_at: {stats['last_created_at']}")
    if stats["samples"]:
        print(f"\n=== Sample hits (first {len(stats['samples'])}) ===")
        random.seed(42)
        for hit in stats["samples"]:
            phones = [m["matched_value"] for m in hit["matches"] if m["category"] == "phone"]
            emails = [m["matched_value"] for m in hit["matches"] if m["category"] == "email"]
            print(f"  fact_id={hit['fact_id']} object_type={hit['object_type']} "
                  f"phones={phones[:3]} emails={emails[:1]}")
            print(f"    preview: {hit['preview']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
