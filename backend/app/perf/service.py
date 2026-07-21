"""性能观测服务：对标 usage/service.py 结构。

数据链路：perf_signals（明细）→ perf_rollups（预聚合）→ API。
百分位策略见 percentile.py（n<20 不返回，n>=20 nearest-rank）。
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

from app.perf.percentile import compute_percentiles, safe_avg, safe_max
from app.time_ranges import bucket_size_minutes, parse_iso, range_bounds_iso


ROLLUP_SCOPES = ("total", "agent_type", "conversation", "session", "project", "model")
MAX_PAGE_SIZE = 200
# R2-A1: summary 端点硬上限，避免 window=all 时全表加载到内存
SUMMARY_ROW_LIMIT = 50000
_VALID_WINDOWS = {"1h", "2h", "3h", "6h", "12h", "24h", "7d", "today", "week", "all"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _where_clauses(
    window: str,
    agent_type: str | None,
    span_type: str | None,
    start_at: str | None,
    end_at: str | None,
) -> tuple[str, list]:
    """构建 WHERE 子句（硬约束：时间范围和 agent_type 必须在 SQL WHERE）。"""
    # I6: 校验 window，无效值直接报错避免全表扫描
    if window not in _VALID_WINDOWS:
        raise ValueError(f"invalid_window:{window}")
    # R2-B3: 显式校验 start_at/end_at，无效值直接报错避免静默退化为全表扫描
    if start_at and parse_iso(start_at) is None:
        raise ValueError(f"invalid_start_at:{start_at}")
    if end_at and parse_iso(end_at) is None:
        raise ValueError(f"invalid_end_at:{end_at}")
    start, end = range_bounds_iso(window, start_at, end_at)
    clauses: list[str] = []
    params: list[str] = []
    if start:
        clauses.append("occurred_at >= ?")
        params.append(start)
    if end:
        clauses.append("occurred_at <= ?")
        params.append(end)
    if agent_type:
        clauses.append("agent_type = ?")
        params.append(agent_type)
    if span_type:
        clauses.append("span_type = ?")
        params.append(span_type)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    return where, params


def _latency_stats(rows: list[sqlite3.Row]) -> dict:
    """从 perf_signal rows 构建延迟统计（含百分位、TTFT、TPS）。

    duration_ms=0 表示"未知"（如 codex llm_call span 无 generation duration 字段），
    不参与百分位/avg/min/max 统计，但 sample_count 仍统计所有行。
    """
    durations = [int(r["duration_ms"]) for r in rows if r["duration_ms"] > 0]
    ttfts = [int(r["ttft_ms"]) for r in rows if r["ttft_ms"] > 0]
    tps_values = [float(r["tps"]) for r in rows if r["tps"] > 0]
    pct = compute_percentiles(durations)
    ttft_pct = compute_percentiles(ttfts)
    success = sum(1 for r in rows if r["status"] == "ok")
    failure = sum(1 for r in rows if r["status"] == "error")
    return {
        "sample_count": len(rows),
        "success_count": success,
        "failure_count": failure,
        "duration_avg_ms": int(safe_avg(durations)),
        "duration_p50_ms": int(pct[50]),
        "duration_p95_ms": int(pct[95]),
        "duration_p99_ms": int(pct[99]),
        "duration_min_ms": min(durations) if durations else 0,
        "duration_max_ms": int(safe_max(durations)),
        "ttft_avg_ms": int(safe_avg(ttfts)) if ttfts else 0,
        "ttft_p50_ms": int(ttft_pct[50]),
        "ttft_p95_ms": int(ttft_pct[95]),
        "tps_avg": round(safe_avg(tps_values), 2) if tps_values else 0,
        "tps_max": round(safe_max(tps_values), 2) if tps_values else 0,
    }


def get_perf_summary(
    conn: sqlite3.Connection,
    window: str = "24h",
    agent_type: str | None = None,
    span_type: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict:
    """顶部指标卡数据：全局快照。"""
    where, params = _where_clauses(window, agent_type, span_type, start_at, end_at)
    # R2-A1: 加 occurred_at desc limit，避免 window=all 全表加载到内存
    rows = conn.execute(
        f"select * from perf_signals {where} order by occurred_at desc limit {SUMMARY_ROW_LIMIT}",
        params,
    ).fetchall()
    # M2: 独立 count 查询，避免截断时 task_count 与 get_perf_tasks.total 不一致
    total_row = conn.execute(
        f"select count(*) as c, count(distinct trace_id) as t from perf_signals {where}", params
    ).fetchone()
    total_signals = int(total_row["c"]) if total_row else 0
    total_tasks = int(total_row["t"]) if total_row else 0
    truncated = len(rows) >= SUMMARY_ROW_LIMIT and total_signals > len(rows)
    by_type: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_type.setdefault(row["span_type"], []).append(row)
    # m9: 按 span_type 字母序排序，避免延迟卡顺序随最新信号跳变
    latency = {st: _latency_stats(by_type[st]) for st in sorted(by_type.keys())}
    llm_rows = by_type.get("llm_call", [])
    llm_success = sum(1 for r in llm_rows if r["status"] == "ok")
    return {
        "window": window,
        "bucket_size_minutes": bucket_size_minutes(window, start_at, end_at),
        "totals": {
            "task_count": total_tasks,
            "llm_call_count": len(llm_rows),
            "tool_call_count": len(by_type.get("tool_call", [])),
            "success_count": llm_success,
            "failure_count": len(llm_rows) - llm_success,
            "success_rate": round(llm_success / len(llm_rows), 4) if llm_rows else 0,
        },
        "latency": latency,
        "sample_count": total_signals,
        # M2: 截断标志，前端据此显示警告横幅
        "truncated": truncated,
    }


def get_perf_tasks(
    conn: sqlite3.Connection,
    window: str = "24h",
    agent_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict:
    """任务列表（按 trace_id 分组）。"""
    page = max(1, page)
    page_size = min(MAX_PAGE_SIZE, max(1, page_size))
    where, params = _where_clauses(window, agent_type, None, start_at, end_at)
    where = f"{where} and trace_id != ''" if where else "where trace_id != ''"
    total_row = conn.execute(
        f"select count(distinct trace_id) as c from perf_signals {where}", params
    ).fetchone()
    total = int(total_row["c"]) if total_row else 0
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        select trace_id,
               min(occurred_at) as started_at,
               coalesce(max(strftime('%Y-%m-%dT%H:%M:%S+00:00', julianday(occurred_at) + duration_ms / 86400000.0)), max(occurred_at)) as ended_at,
               sum(case when span_type != 'task' then 1 else 0 end) as call_count,
               sum(case when span_type = 'llm_call' then 1 else 0 end) as llm_call_count,
               sum(case when span_type = 'tool_call' then 1 else 0 end) as tool_call_count,
               sum(case when status = 'ok' then 1 else 0 end) as success_count,
               sum(case when status = 'error' then 1 else 0 end) as failure_count,
               sum(duration_ms) as total_duration_ms,
               coalesce(max(case when span_type = 'task' then agent_type end), max(agent_type)) as agent_type,
               max(conversation_ref) as conversation_ref,
               coalesce(nullif(max(case when span_type = 'task' then fact_id end), ''), nullif(max(fact_id), '')) as fact_id,
               max(case when span_type = 'task' then duration_ms else 0 end) as task_duration_ms,
               coalesce(nullif(max(case when span_type = 'task' then error end), ''), nullif(max(error), '')) as task_error,
               case when sum(case when status = 'error' then 1 else 0 end) > 0 then 'error'
                    when sum(case when status = 'ok' then 1 else 0 end) > 0 then 'ok'
                    else '' end as task_status
        from perf_signals {where}
        group by trace_id
        order by started_at desc, trace_id desc
        limit ? offset ?
        """,
        params + [page_size, offset],
    ).fetchall()
    return {
        "window": window,
        "page": page,
        "page_size": page_size,
        "total": total,
        "tasks": [dict(row) for row in rows],
    }


def _span_payload(row: sqlite3.Row) -> dict:
    return {
        "signal_id": row["signal_id"],
        "fact_id": row["fact_id"],
        "span_id": row["span_id"],
        "parent_span_id": row["parent_span_id"],
        "span_type": row["span_type"],
        "span_name": row["span_name"],
        "duration_ms": row["duration_ms"],
        "ttft_ms": row["ttft_ms"],
        "tps": row["tps"],
        "status": row["status"],
        "error": row["error"],
        "model": row["model"],
        "tool_name": row["tool_name"],
        "occurred_at": row["occurred_at"],
    }


def get_perf_task_detail(conn: sqlite3.Connection, trace_id: str) -> dict | None:
    """单个任务详情：spans 列表 + 调用明细 + 会话期间关键事件。"""
    # m11: 与 get_perf_call_timeline 一致加 limit 1000，避免异常大 trace OOM
    rows = conn.execute(
        "select * from perf_signals where trace_id = ? order by occurred_at, signal_id limit 1000",
        (trace_id,),
    ).fetchall()
    if not rows:
        return None
    spans = [_span_payload(row) for row in rows]
    task_row = next((r for r in rows if r["span_type"] == "task"), None)
    # R2-A4: ended_at = max(occurred_at + duration_ms)，不是 max(occurred_at)
    end_times = []
    for r in rows:
        parsed = parse_iso(r["occurred_at"])
        if parsed is not None:
            end_times.append(parsed + timedelta(milliseconds=int(r["duration_ms"])))
    ended_at = max(end_times).replace(microsecond=0).isoformat() if end_times else rows[-1]["occurred_at"]
    # R2-X27: call_count 排除 task span，与 get_perf_tasks 保持一致
    call_count = sum(1 for r in rows if r["span_type"] != "task")
    # R2-E6: task_status 与 get_perf_tasks 一致（rolled up），便于抽屉区分任务整体状态与 task span 自身状态
    error_count = sum(1 for r in rows if r["status"] == "error")
    ok_count = sum(1 for r in rows if r["status"] == "ok")
    task_status = "error" if error_count > 0 else ("ok" if ok_count > 0 else "")
    # P1-1: rolled-up task_error，与 get_perf_tasks 同口径。
    # 优先 task span 自身 error；为空则回退到任一子 span error。
    # 避免抽屉元数据状态标签（用 task_error）与列表不一致：task span ok 但子 span interrupted
    # 时，列表显示"已中断"，抽屉也应显示"已中断"而非"失败"。
    task_error = ""
    if task_row and task_row["error"]:
        task_error = task_row["error"]
    else:
        error_row = next((r for r in rows if r["error"]), None)
        if error_row:
            task_error = error_row["error"]
    # 会话期间关键事件：让用户在抽屉内即可理解"失败时发生了什么"，
    # 不用跳到会话页。只取 risk/error 类型（文件变更、破坏性操作、工具失败等），
    # 排除 perf/usage/unknown/content/tool（噪声或已在 spans 内）。
    # 注意：不限时间范围——失败原因可能发生在 task 开始前（如上一个 turn 的文件变更
    # 触发用户中断）。会话级 risk/error 数量有限，limit 50 足够。
    # P2-7: 取首个非空 conversation_ref，避免首行空值导致 context_events 整体丢失。
    conversation_ref = next((r["conversation_ref"] for r in rows if r["conversation_ref"]), "")
    context_events = _get_task_context_events(conn, conversation_ref)
    return {
        "trace_id": trace_id,
        "task": _span_payload(task_row) if task_row else None,
        "spans": spans,
        "agent_type": task_row["agent_type"] if task_row else rows[0]["agent_type"],
        "conversation_ref": conversation_ref,
        "started_at": rows[0]["occurred_at"],
        "ended_at": ended_at,
        "call_count": call_count,
        "task_status": task_status,
        "task_error": task_error,
        "context_events": context_events,
    }


def _get_task_context_events(conn: sqlite3.Connection, conversation_ref: str) -> list[dict]:
    """查询会话内的关键 facts（risk/error 类型），帮助用户理解失败上下文。

    返回整个会话的 risk/error facts（不限时间范围），因为失败原因可能
    发生在 task 开始前（如上一个 turn 的文件变更触发用户中断）。
    按 occurred_at desc 排序取最近 50 条：失败通常由最近的事件触发，
    长会话里最早的事件对用户理解当前失败帮助不大。
    """
    if not conversation_ref:
        return []
    rows = conn.execute(
        """
        select fact_id, fact_type, category, normalized_event_type, severity,
               summary, occurred_at
        from observed_facts
        where conversation_ref = ?
          and fact_type in ('risk', 'error')
        order by occurred_at desc
        limit 50
        """,
        (conversation_ref,),
    ).fetchall()
    return [
        {
            "fact_id": r["fact_id"],
            "fact_type": r["fact_type"],
            "category": r["category"],
            "normalized_event_type": r["normalized_event_type"],
            "severity": r["severity"],
            "summary": r["summary"] or "",
            "occurred_at": r["occurred_at"],
        }
        for r in rows
    ]


def get_perf_call_timeline(
    conn: sqlite3.Connection, trace_id: str, span_type: str | None = None
) -> list[dict]:
    """调用明细时间线。"""
    where = "where trace_id = ?"
    params: list[str] = [trace_id]
    if span_type:
        where += " and span_type = ?"
        params.append(span_type)
    # R2-X5: 加 limit 1000 避免单个 trace 下 span 过多导致内存溢出
    rows = conn.execute(
        f"select * from perf_signals {where} order by occurred_at, signal_id limit 1000", params
    ).fetchall()
    return [_span_payload(row) for row in rows]


def get_failure_timeline(
    conn: sqlite3.Connection,
    window: str = "24h",
    agent_type: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> list[dict]:
    """失败时间线：status=error 的 perf_signals 按时间倒序。"""
    where, params = _where_clauses(window, agent_type, None, start_at, end_at)
    where = f"{where} and status = 'error'" if where else "where status = 'error'"
    rows = conn.execute(
        f"""
        select signal_id, fact_id, trace_id, span_type, span_name, tool_name, duration_ms,
               error, occurred_at, agent_type, conversation_ref
        from perf_signals {where}
        order by occurred_at desc
        limit 200
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _scope_value(row: sqlite3.Row, scope: str) -> str:
    if scope == "total":
        return "all"
    if scope == "agent_type":
        return row["agent_type"] or "unknown"
    if scope == "conversation":
        return row["conversation_ref"] or "unknown"
    if scope == "session":
        return row["session_ref"] or "unknown"
    if scope == "project":
        return row["project_ref"] or "unknown"
    if scope == "model":
        return row["model"] or "unknown"
    return "unknown"


def build_perf_rollups(conn: sqlite3.Connection, window: str = "24h") -> dict:
    """预聚合：扫 perf_signals，计算 P50/P95/P99，写 perf_rollups。"""
    where, params = _where_clauses(window, None, None, None, None)
    rows = conn.execute(f"select * from perf_signals {where}", params).fetchall()
    if not rows:  # I7: 无新数据时不删除已有 rollups，避免误清空历史聚合
        return {"window": window, "groups": 0, "signals": 0}
    conn.execute("delete from perf_rollups where window = ?", (window,))
    groups: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        for scope in ROLLUP_SCOPES:
            scope_value = _scope_value(row, scope)
            key = (scope, scope_value, row["span_type"])
            groups.setdefault(key, []).append(row)
    now = _now()
    for (scope, scope_value, span_type), group_rows in groups.items():
        stats = _latency_stats(group_rows)
        # M4: 用 sha256 hash 避免转义碰撞（R2-X8 的 replace(':', '_') 在 '_' 原生存在时仍会碰撞）
        safe_scope_value = hashlib.sha256((scope_value or "").encode("utf-8")).hexdigest()[:16]
        rollup_id = f"{window}:{scope}:{safe_scope_value}:{span_type}"
        conn.execute(
            """
            insert into perf_rollups (
              rollup_id, window, scope, scope_value, span_type,
              sample_count, success_count, failure_count,
              duration_avg_ms, duration_p50_ms, duration_p95_ms, duration_p99_ms,
              duration_min_ms, duration_max_ms,
              ttft_avg_ms, ttft_p50_ms, ttft_p95_ms,
              tps_avg, tps_max, built_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rollup_id, window, scope, scope_value, span_type,
                stats["sample_count"], stats["success_count"], stats["failure_count"],
                stats["duration_avg_ms"], stats["duration_p50_ms"], stats["duration_p95_ms"], stats["duration_p99_ms"],
                stats["duration_min_ms"], stats["duration_max_ms"],
                stats["ttft_avg_ms"], stats["ttft_p50_ms"], stats["ttft_p95_ms"],
                stats["tps_avg"], stats["tps_max"], now,
            ),
        )
    conn.commit()
    return {"window": window, "groups": len(groups), "signals": len(rows)}


def get_perf_rollups(
    conn: sqlite3.Connection, window: str = "24h", scope: str | None = None
) -> list[dict]:
    """读取预聚合明细（debug 用）。"""
    where = "where window = ?"
    params: list[str] = [window]
    if scope:
        where += " and scope = ?"
        params.append(scope)
    rows = conn.execute(
        f"select * from perf_rollups {where} order by scope, scope_value, span_type", params
    ).fetchall()
    return [dict(row) for row in rows]
