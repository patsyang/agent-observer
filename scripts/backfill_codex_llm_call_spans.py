"""回填历史 codex task span 的 llm_call span。

为 span_name='codex_turn' 且 ttft_ms > 0 的 task span 插入对应的 llm_call span，
并把 task span 的 ttft_ms 置 0（TTFT 迁移到 llm_call span，避免重复统计）。

修复背景：旧版 codex collector 只产出 task span（ttft_ms 挂在 task span 上），
新版 collector 拆分 llm_call span 后 task span ttft_ms=0。本脚本把历史数据对齐到新格式，
使"LLM 调用"指标卡和延迟分布卡有真实数据。

signal_id 构造与 ingest 一致：
  task span:  perf-{fact_id}-task-{turn_id[:16]}
  llm span:   perf-{fact_id}-llm-{turn_id[:16]}  （REPLACE '-task-' -> '-llm-'）

用法：
  python scripts/backfill_codex_llm_call_spans.py --dry-run  # 预览
  python scripts/backfill_codex_llm_call_spans.py --apply     # 执行
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db.connection import write_lock
from app.perf.service import build_perf_rollups


def backfill(db_path: str | Path, apply: bool = False) -> None:
    with write_lock(db_path) as conn:
        # 1. 统计待回填数量
        count_row = conn.execute(
            "select count(*) as c from perf_signals "
            "where span_type='task' and span_name='codex_turn' and ttft_ms > 0"
        ).fetchone()
        total = int(count_row["c"]) if count_row else 0
        print(f"待回填的 codex task span（ttft_ms>0）：{total}")

        if total == 0:
            print("无需回填。")
            return

        if not apply:
            sample = conn.execute(
                "select signal_id, fact_id, span_id, ttft_ms from perf_signals "
                "where span_type='task' and span_name='codex_turn' and ttft_ms > 0 limit 5"
            ).fetchall()
            print("\n预览（前 5 条）：")
            for r in sample:
                llm_signal_id = r["signal_id"].replace("-task-", "-llm-")
                llm_span_id = r["span_id"].replace("task-", "llm-", 1)
                print(f"  task: {r['signal_id']} (span={r['span_id']}, ttft={r['ttft_ms']}ms)")
                print(f"  llm:  {llm_signal_id} (span={llm_span_id}, ttft={r['ttft_ms']}ms)")
            print(f"\n共 {total} 条。使用 --apply 执行回填。")
            return

        # 2. 单事务执行：INSERT llm_call span + UPDATE task span ttft_ms=0
        try:
            insert_result = conn.execute(
                """
                insert into perf_signals (
                  signal_id, fact_id, trace_id, parent_span_id, span_id, span_type, span_name,
                  duration_ms, ttft_ms, tps, status, error, model, tool_name,
                  agent_type, conversation_ref, session_ref, project_ref, occurred_at
                )
                select
                  replace(signal_id, '-task-', '-llm-'),
                  fact_id,
                  trace_id,
                  span_id,
                  replace(span_id, 'task-', 'llm-'),
                  'llm_call',
                  'codex_generation',
                  duration_ms,
                  ttft_ms,
                  tps,
                  status,
                  error,
                  model,
                  tool_name,
                  agent_type,
                  conversation_ref,
                  session_ref,
                  project_ref,
                  occurred_at
                from perf_signals
                where span_type = 'task'
                  and span_name = 'codex_turn'
                  and ttft_ms > 0
                on conflict(signal_id) do nothing
                """
            )
            inserted = insert_result.rowcount
            print(f"插入 llm_call span：{inserted} 条")

            update_result = conn.execute(
                "update perf_signals set ttft_ms = 0 "
                "where span_type = 'task' and span_name = 'codex_turn' and ttft_ms > 0"
            )
            updated = update_result.rowcount
            print(f"置 0 task span ttft_ms：{updated} 条")

            conn.commit()
            print("回填完成。")

            # 3. 重建 perf_rollups（前端不直接读，但 debug 端点用）
            print("\n重建 perf_rollups...")
            for window in ["24h", "7d"]:
                result = build_perf_rollups(conn, window=window)
                print(f"  {window}: groups={result['groups']}, signals={result['signals']}")
            conn.commit()
            print("perf_rollups 重建完成。")
        except Exception as e:
            conn.rollback()
            print(f"回填失败，已回滚：{e}")
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="回填历史 codex task span 的 llm_call span")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不执行")
    parser.add_argument("--apply", action="store_true", help="执行回填")
    parser.add_argument("--db", default=None, help="数据库路径（默认用 connection.py 的默认路径）")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("请指定 --dry-run 或 --apply")

    db_path = args.db if args.db else None
    backfill(db_path, apply=args.apply)


if __name__ == "__main__":
    main()

