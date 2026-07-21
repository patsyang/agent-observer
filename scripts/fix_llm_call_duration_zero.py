"""修复 llm_call span 的 duration_ms：把 codex_generation 的 duration_ms 改为 0。

背景：Slice A 错误地把 turn 的 duration_ms（含工具调用、等待）当作 LLM generation duration，
导致前端显示"LLM 调用耗时 23 分钟"。codex turn 事件没有 LLM generation duration 字段，
所以 llm_call span 的 duration_ms 应为 0（未知），不参与百分位统计。

用法：
  python scripts/fix_llm_call_duration_zero.py --dry-run  # 预览
  python scripts/fix_llm_call_duration_zero.py --apply     # 执行
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db.connection import write_lock
from app.perf.service import build_perf_rollups


def fix(db_path: str | Path, apply: bool = False) -> None:
    with write_lock(db_path) as conn:
        # 1. 统计待修复数量
        count_row = conn.execute(
            "select count(*) as c from perf_signals "
            "where span_type='llm_call' and span_name='codex_generation' and duration_ms > 0"
        ).fetchone()
        total = int(count_row["c"]) if count_row else 0
        print(f"待修复的 llm_call span（duration_ms>0）：{total}")

        if total == 0:
            print("无需修复。")
            return

        if not apply:
            sample = conn.execute(
                "select signal_id, duration_ms, ttft_ms from perf_signals "
                "where span_type='llm_call' and span_name='codex_generation' and duration_ms > 0 limit 5"
            ).fetchall()
            print("\n预览（前 5 条）：")
            for r in sample:
                print(f"  {r['signal_id']}: duration={r['duration_ms']}ms -> 0, ttft={r['ttft_ms']}ms (保留)")
            print(f"\n共 {total} 条。使用 --apply 执行修复。")
            return

        # 2. 单事务执行：UPDATE llm_call span duration_ms=0
        try:
            result = conn.execute(
                "update perf_signals set duration_ms = 0 "
                "where span_type = 'llm_call' and span_name = 'codex_generation' and duration_ms > 0"
            )
            updated = result.rowcount
            print(f"置 0 llm_call span duration_ms：{updated} 条")
            conn.commit()
            print("修复完成。")

            # 3. 重建 perf_rollups
            print("\n重建 perf_rollups...")
            for window in ["24h", "7d"]:
                result = build_perf_rollups(conn, window=window)
                print(f"  {window}: groups={result['groups']}, signals={result['signals']}")
            conn.commit()
            print("perf_rollups 重建完成。")
        except Exception as e:
            conn.rollback()
            print(f"修复失败，已回滚：{e}")
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="修复 llm_call span duration_ms=0")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不执行")
    parser.add_argument("--apply", action="store_true", help="执行修复")
    parser.add_argument("--db", default=None, help="数据库路径（默认用 connection.py 的默认路径）")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("请指定 --dry-run 或 --apply")

    db_path = args.db if args.db else None
    fix(db_path, apply=args.apply)


if __name__ == "__main__":
    main()
