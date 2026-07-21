"""perf 模块最小测试：覆盖百分位、汇总、预聚合、window 校验、span_id 唯一性、task_status 聚合。"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from app.db.connection import connect
from app.perf.percentile import compute_percentiles, safe_avg, safe_max
from app.perf.service import (
    _latency_stats,
    _where_clauses,
    build_perf_rollups,
    get_failure_timeline,
    get_perf_summary,
    get_perf_task_detail,
    get_perf_tasks,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _insert_fact(
    conn: sqlite3.Connection,
    fact_id: str,
    occurred_at: str = "",
    *,
    fact_type: str = "perf",
    category: str = "task",
    summary: str = "test fact",
    conversation_ref: str = "",
) -> None:
    """插入最小 observed_facts 行，满足 perf_signals 的 FK 约束。

    默认 fact_type=perf/category=task 保持与旧测试一致；
    context_events 测试用 fact_type='risk'/'error' + conversation_ref 触发同会话关联。
    """
    conn.execute(
        """
        insert into observed_facts (
          fact_id, source_event_id, batch_id, collector_id, source_id, source, agent_type, source_kind,
          fact_type, category, normalized_event_type, quality,
          severity, summary, occurred_at, promoted_to_signal, source_refs_json,
          source_specific_json, content_preview, raw_available, raw_status, conversation_ref,
          session_ref, source_event_type, source_path_hash, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '{}', '{}', '', 0, '', ?, '', '', '', ?)
        """,
        (
            fact_id, fact_id, "batch-test", "collector-test", "src-test", "workbuddy", "workbuddy", "workbuddy_local",
            fact_type, category, "trace", "high",
            "low", summary, occurred_at or _now(),
            conversation_ref,
            _now(),
        ),
    )


def _insert_perf_signal(
    conn: sqlite3.Connection,
    *,
    signal_id: str,
    fact_id: str,
    trace_id: str = "trace-1",
    span_id: str = "span-1",
    span_type: str = "llm_call",
    duration_ms: int = 100,
    ttft_ms: int = 0,
    tps: float = 0.0,
    status: str = "ok",
    model: str = "",
    agent_type: str = "workbuddy",
    conversation_ref: str = "conv-1",
    occurred_at: str = "",
) -> None:
    conn.execute(
        """
        insert into perf_signals (
          signal_id, fact_id, trace_id, parent_span_id, span_id, span_type, span_name,
          duration_ms, ttft_ms, tps, status, error, model, tool_name,
          agent_type, conversation_ref, session_ref, project_ref, occurred_at
        ) values (?, ?, ?, '', ?, ?, '', ?, ?, ?, ?, '', ?, '', ?, ?, '', '', ?)
        """,
        (
            signal_id, fact_id, trace_id, span_id, span_type,
            duration_ms, ttft_ms, tps, status, model,
            agent_type, conversation_ref, occurred_at or _now(),
        ),
    )


# ---------- percentile.py ----------

def test_compute_percentiles_below_threshold_returns_zeros():
    """n<20 时百分位返回 0（plan §5.3 分段策略）。"""
    result = compute_percentiles([10, 20, 30, 40])
    assert result[50] == 0.0
    assert result[95] == 0.0
    assert result[99] == 0.0


def test_compute_percentiles_above_threshold_nearest_rank():
    """n>=20 使用 nearest-rank 方法。"""
    values = list(range(1, 21))  # 1..20
    result = compute_percentiles(values)
    # P50: ceil(0.5*20)=10 → sorted[9]=10
    assert result[50] == 10
    # P95: ceil(0.95*20)=19 → sorted[18]=19
    assert result[95] == 19
    # P99: ceil(0.99*20)=20 → sorted[19]=20
    assert result[99] == 20


def test_safe_avg_and_max_handle_empty():
    assert safe_avg([]) == 0
    assert safe_max([]) == 0


# ---------- service.py: _where_clauses (I6) ----------

def test_where_clauses_invalid_window_raises(tmp_path):
    """I6: 无效 window 应抛 ValueError，避免全表扫描。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        with pytest.raises(ValueError, match="invalid_window"):
            _where_clauses("invalid", None, None, None, None)


def test_where_clauses_valid_window_allows_all():
    """window='all' 合法，不产生时间过滤。"""
    where, params = _where_clauses("all", None, None, None, None)
    assert where == ""
    assert params == []


# ---------- service.py: get_perf_summary ----------

def test_perf_summary_empty_database(tmp_path):
    """空库返回零值汇总。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        result = get_perf_summary(conn, window="24h")
    assert result["sample_count"] == 0
    assert result["totals"]["task_count"] == 0
    assert result["totals"]["llm_call_count"] == 0


def test_perf_summary_with_signals(tmp_path):
    """插入 perf_signals 后汇总正确。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        _insert_perf_signal(conn, signal_id="perf-fact-1-task", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-fact-1-llm", fact_id="fact-1", span_id="span-llm-1",
                           span_type="llm_call", duration_ms=200, ttft_ms=50, tps=15.5, status="ok",
                           model="gpt-4", occurred_at=now)
        result = get_perf_summary(conn, window="24h")
    assert result["sample_count"] == 2
    assert result["totals"]["task_count"] == 1
    assert result["totals"]["llm_call_count"] == 1
    assert result["totals"]["success_count"] == 1
    assert result["latency"]["llm_call"]["duration_avg_ms"] == 200


# ---------- service.py: build_perf_rollups (I7) ----------

def test_build_perf_rollups_empty_returns_early(tmp_path):
    """I7: 无数据时不删除已有 rollups，直接返回。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        result = build_perf_rollups(conn, window="24h")
    assert result["groups"] == 0
    assert result["signals"] == 0


def test_build_perf_rollups_with_data(tmp_path):
    """有数据时构建 rollups。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        _insert_perf_signal(conn, signal_id="perf-fact-1-llm", fact_id="fact-1", span_id="span-1",
                           span_type="llm_call", duration_ms=100, status="ok", occurred_at=now)
        result = build_perf_rollups(conn, window="24h")
    assert result["signals"] == 1
    assert result["groups"] >= 1


# ---------- service.py: get_perf_tasks (I4) ----------

def test_task_status_failure_priority(tmp_path):
    """I4: task_status 应优先 error（修复前 max() 会让 ok 覆盖 error）。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        # 同一 trace 下 task span 有 ok 和 error 两种状态
        _insert_perf_signal(conn, signal_id="perf-fact-1-task-ok", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok", trace_id="trace-x", occurred_at=now)
        # 注意：signal_id 唯一，但同 trace 下只能有一个 task span。这里用第二个 fact 模拟多 trace
        _insert_fact(conn, "fact-2", now)
        _insert_perf_signal(conn, signal_id="perf-fact-2-task-err", fact_id="fact-2", span_id="trace-root",
                           span_type="task", duration_ms=300, status="error", trace_id="trace-y", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-fact-2-llm", fact_id="fact-2", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="ok", trace_id="trace-y", occurred_at=now)
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    assert tasks["trace-y"]["task_status"] == "error"
    assert tasks["trace-x"]["task_status"] == "ok"


def test_task_status_from_child_span_failure(tmp_path):
    """R2-A2: task span 为 ok 但子 span (llm_call) 为 error 时，task_status 应为 error。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        # task span 状态 ok
        _insert_perf_signal(conn, signal_id="perf-r2a2-task", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok", trace_id="trace-r2a2", occurred_at=now)
        # 子 llm_call span 状态 error
        _insert_perf_signal(conn, signal_id="perf-r2a2-llm-err", fact_id="fact-1", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="error", trace_id="trace-r2a2", occurred_at=now)
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    # 修复前：task span 为 ok → task_status="ok"（错误）
    # 修复后：子 span 有 error → task_status="error"（正确）
    assert tasks["trace-r2a2"]["task_status"] == "error"


# ---------- workbuddy collector: _trace_perf_projection (I2) ----------

def test_trace_perf_projection_span_id_uniqueness():
    """I2: 重复 spanId 应追加后缀，避免 signal_id 冲突。"""
    from app.collector_client.sources.workbuddy import _trace_perf_projection

    trace = {"traceId": "trace-abc", "duration": 1000, "status": "ok", "name": "test-trace"}
    spans = [
        {"spanId": "span-1", "type": "generation", "duration": 200, "status": "ok"},
        {"spanId": "span-1", "type": "generation", "duration": 300, "status": "ok"},  # 重复 spanId
        {"spanId": "span-2", "type": "function", "duration": 50, "status": "ok"},
    ]
    base = {"occurred_at": _now()}
    _projection, perf_signals = _trace_perf_projection(trace, spans, base)
    span_ids = [s["span_id"] for s in perf_signals]
    # 所有 span_id 唯一
    assert len(span_ids) == len(set(span_ids)), f"span_ids 有重复: {span_ids}"
    # 包含原始 span-1 和带后缀的 span-1-1
    assert "span-1" in span_ids
    assert "span-1-1" in span_ids
    assert "span-2" in span_ids


# ---------- R2-A4: ended_at = max(occurred_at + duration_ms) ----------

def test_task_detail_ended_at_includes_duration(tmp_path):
    """R2-A4: ended_at = max(occurred_at + duration_ms)，不是 max(occurred_at)。"""
    base_time = "2026-07-18T10:00:00+00:00"
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", base_time)
        # task span: 10:00:00 + 5000ms = 10:00:05
        _insert_perf_signal(conn, signal_id="perf-r2a4-task", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=5000, status="ok",
                           trace_id="trace-r2a4", occurred_at=base_time)
        # llm_call span: 10:00:01 + 100ms = 10:00:01.1（晚开始但早结束）
        _insert_perf_signal(conn, signal_id="perf-r2a4-llm", fact_id="fact-1", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="ok",
                           trace_id="trace-r2a4", occurred_at="2026-07-18T10:00:01+00:00")
        result = get_perf_task_detail(conn, "trace-r2a4")
    # 修复前：ended_at = "10:00:01"（最后一个 span 的 occurred_at）
    # 修复后：ended_at = "10:00:05"（task span 的 occurred_at + duration_ms）
    assert "10:00:05" in result["ended_at"]


# ---------- R2-X27: call_count 排除 task span ----------

def test_call_count_excludes_task_span(tmp_path):
    """R2-X27: call_count 排除 task span，只统计实际调用数。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        _insert_perf_signal(conn, signal_id="perf-r2x27-task", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-r2x27", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-r2x27-llm-1", fact_id="fact-1", span_id="span-llm-1",
                           span_type="llm_call", duration_ms=100, status="ok",
                           trace_id="trace-r2x27", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-r2x27-llm-2", fact_id="fact-1", span_id="span-llm-2",
                           span_type="llm_call", duration_ms=200, status="ok",
                           trace_id="trace-r2x27", occurred_at=now)
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    # 修复前：call_count=3（包含 task span）
    # 修复后：call_count=2（排除 task span）
    assert tasks["trace-r2x27"]["call_count"] == 2


# ---------- R2-A3: agent_type 使用 task span 的值 ----------

def test_agent_type_uses_task_span_value(tmp_path):
    """R2-A3: agent_type 应使用 task span 的值，不是 max(agent_type)。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        # task span 的 agent_type 是 "codex"
        _insert_perf_signal(conn, signal_id="perf-r2a3-task", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-r2a3", agent_type="codex", occurred_at=now)
        # llm_call span 的 agent_type 是 "workbuddy"（字母序在 "codex" 之后）
        _insert_perf_signal(conn, signal_id="perf-r2a3-llm", fact_id="fact-1", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="ok",
                           trace_id="trace-r2a3", agent_type="workbuddy", occurred_at=now)
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    # 修复前：max(agent_type) = "workbuddy"（字母序最大值，非确定性）
    # 修复后：task span 的 agent_type = "codex"
    assert tasks["trace-r2a3"]["agent_type"] == "codex"


# ---------- R2-B3: 无效 start_at/end_at 抛 ValueError ----------

def test_where_clauses_invalid_start_at_raises(tmp_path):
    """R2-B3: 无效 start_at 应抛 ValueError，避免静默退化为全表扫描。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        with pytest.raises(ValueError, match="invalid_start_at"):
            _where_clauses("24h", None, None, "not-a-date", None)


def test_where_clauses_invalid_end_at_raises(tmp_path):
    """R2-B3: 无效 end_at 应抛 ValueError。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        with pytest.raises(ValueError, match="invalid_end_at"):
            _where_clauses("24h", None, None, None, "invalid")


# ---------- R2-X8: rollup_id 碰撞修复（M4: sha256 hash） ----------

def test_rollup_id_no_collision_with_colon_in_scope_value(tmp_path):
    """R2-X8 + M4: scope_value 含 ':' 时 rollup_id 用 sha256 hash 避免碰撞。

    旧实现 replace(':', '_') 在 '_' 原生存在时仍会碰撞：
      "conv:with:colons" → "conv_with_colons"
      "conv_with_colons" → "conv_with_colons"  (碰撞！)
    M4 改用 sha256(scope_value)[:16]，两个不同 scope_value 必产生不同 hash。
    """
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        # 两个会碰撞的 scope_value
        _insert_perf_signal(conn, signal_id="perf-r2x8-a", fact_id="fact-1", span_id="span-1",
                           span_type="llm_call", duration_ms=100, status="ok",
                           conversation_ref="conv:with:colons", trace_id="trace-a",
                           occurred_at=now)
        _insert_fact(conn, "fact-2", now)
        _insert_perf_signal(conn, signal_id="perf-r2x8-b", fact_id="fact-2", span_id="span-2",
                           span_type="llm_call", duration_ms=100, status="ok",
                           conversation_ref="conv_with_colons", trace_id="trace-b",
                           occurred_at=now)
        build_perf_rollups(conn, window="24h")
        rollups = conn.execute(
            "select rollup_id, scope_value from perf_rollups where scope = 'conversation'"
        ).fetchall()
    assert len(rollups) >= 2
    # scope_value 保持原始值
    scope_values = {r["scope_value"] for r in rollups}
    assert "conv:with:colons" in scope_values
    assert "conv_with_colons" in scope_values
    # M4: rollup_id 用 sha256 hash，两个不同 scope_value 必产生不同 rollup_id
    rollup_ids = {r["rollup_id"] for r in rollups}
    assert len(rollup_ids) == len(rollups), f"rollup_id 有碰撞: {rollup_ids}"
    # 确认 rollup_id 中的 scope_value 部分是 hash（16 位 hex），非原始值
    for r in rollups:
        # rollup_id 格式: {window}:{scope}:{hash16}:{span_type}
        parts = r["rollup_id"].split(":")
        hash_part = parts[2] if len(parts) >= 4 else ""
        assert len(hash_part) == 16, f"hash 部分长度异常: {hash_part}"
        assert all(c in "0123456789abcdef" for c in hash_part), \
            f"hash 部分非 hex: {hash_part}"
        # 原始 scope_value 不应出现在 rollup_id 中（避免 ':' 注入）
        assert r["scope_value"] not in r["rollup_id"], \
            f"原始 scope_value 泄漏到 rollup_id: {r['rollup_id']}"


# ---------- R2-E6: task_detail 的 task_status 与任务列表一致 ----------

def test_task_detail_task_status_matches_rolled_up(tmp_path):
    """R2-E6: task_detail.task_status 应为 rolled up 值（子 span 有 error 则 error），与任务列表一致。

    场景：task span 自身 ok，但子 llm_call span 为 error。
    修复前：抽屉只展示 task span 的自身状态（ok），与任务列表（error）不一致。
    修复后：抽屉元数据网格新增 task_status（error），与任务列表一致。
    """
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        # task span 自身状态 ok
        _insert_perf_signal(conn, signal_id="perf-r2e6-task", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-r2e6", occurred_at=now)
        # 子 llm_call span 状态 error
        _insert_perf_signal(conn, signal_id="perf-r2e6-llm-err", fact_id="fact-1", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="error",
                           trace_id="trace-r2e6", occurred_at=now)
        detail = get_perf_task_detail(conn, "trace-r2e6")
        tasks = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks_by_trace = {t["trace_id"]: t for t in tasks["tasks"]}
    # 抽屉的 task_status 与任务列表的 task_status 一致
    assert detail["task_status"] == "error"
    assert tasks_by_trace["trace-r2e6"]["task_status"] == "error"
    # task span 自身状态仍为 ok（区分整体状态与 span 自身状态）
    assert detail["task"]["status"] == "ok"


def test_task_detail_task_status_all_ok(tmp_path):
    """R2-E6: 所有 span 都 ok 时 task_status='ok'。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-1", now)
        _insert_perf_signal(conn, signal_id="perf-r2e6ok-task", fact_id="fact-1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-r2e6ok", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-r2e6ok-llm", fact_id="fact-1", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="ok",
                           trace_id="trace-r2e6ok", occurred_at=now)
        detail = get_perf_task_detail(conn, "trace-r2e6ok")
    assert detail["task_status"] == "ok"


# ---------- M1: 分页确定性（started_at desc, trace_id desc） ----------

def test_tasks_pagination_deterministic_with_same_started_at(tmp_path):
    """M1: 多个任务 started_at 相同时，按 trace_id desc 排序，分页无重复/遗漏。

    旧实现只按 started_at desc 排序，相同 started_at 时顺序不确定，
    导致分页可能出现重复或遗漏行。
    M1 增加 trace_id desc 作为第二排序键。
    """
    base_time = "2026-07-18T10:00:00+00:00"
    trace_ids = ["trace-c", "trace-b", "trace-a"]
    with connect(tmp_path / "observer.sqlite") as conn:
        for i, tid in enumerate(trace_ids):
            _insert_fact(conn, f"fact-m1-{i}", base_time)
            _insert_perf_signal(conn, signal_id=f"perf-m1-task-{i}", fact_id=f"fact-m1-{i}",
                               span_id="trace-root", span_type="task", duration_ms=500,
                               status="ok", trace_id=tid, occurred_at=base_time)
        # page_size=2，分两页
        page1 = get_perf_tasks(conn, window="24h", page=1, page_size=2)
        page2 = get_perf_tasks(conn, window="24h", page=2, page_size=2)
    # total = 3
    assert page1["total"] == 3
    # 第一页：trace-c, trace-b（trace_id desc）
    page1_ids = [t["trace_id"] for t in page1["tasks"]]
    assert page1_ids == ["trace-c", "trace-b"]
    # 第二页：trace-a
    page2_ids = [t["trace_id"] for t in page2["tasks"]]
    assert page2_ids == ["trace-a"]
    # 无重复
    all_ids = page1_ids + page2_ids
    assert len(all_ids) == len(set(all_ids)), f"分页有重复: {all_ids}"
    assert set(all_ids) == set(trace_ids), f"分页有遗漏: {all_ids}"


# ---------- Slice 2: fact_id 字段返回（前端"查看会话"跳转依赖） ----------

def test_get_perf_tasks_returns_fact_id(tmp_path):
    """Slice 2: get_perf_tasks 返回的 task 行包含 fact_id（优先取 task span 的 fact_id）。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-task-A", now)
        _insert_fact(conn, "fact-llm-A", now)
        _insert_perf_signal(conn, signal_id="perf-s2-task-a", fact_id="fact-task-A", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-s2-a", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-s2-llm-a", fact_id="fact-llm-A", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="ok",
                           trace_id="trace-s2-a", occurred_at=now)
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    # task span 的 fact_id 优先
    assert tasks["trace-s2-a"]["fact_id"] == "fact-task-A"


def test_get_perf_tasks_fact_id_falls_back_to_child_when_task_empty(tmp_path):
    """Slice 2 + S2 修复：task span 的 fact_id 为空串时，回退到子 span 的 fact_id。

    旧 SQL: coalesce(max(case when task then fact_id end), max(fact_id))
    空串 '' 非 NULL，coalesce 直接返回 ''，子 span 的有效 fact_id 被遮蔽。
    修复后: coalesce(nullif(..., ''), nullif(max(fact_id), ''))
    """
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        # task span 的 fact_id 为空串
        _insert_fact(conn, "", now)
        _insert_perf_signal(conn, signal_id="perf-s2-task-empty", fact_id="", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-s2-empty", occurred_at=now)
        # 子 span 有真实 fact_id
        _insert_fact(conn, "fact-child-real", now)
        _insert_perf_signal(conn, signal_id="perf-s2-llm-real", fact_id="fact-child-real", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="ok",
                           trace_id="trace-s2-empty", occurred_at=now)
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    # 修复前：fact_id = ""（空串，前端显示 "-"）
    # 修复后：fact_id = "fact-child-real"（回退到子 span）
    assert tasks["trace-s2-empty"]["fact_id"] == "fact-child-real"


def test_get_perf_task_detail_returns_fact_id_in_spans(tmp_path):
    """Slice 2: get_perf_task_detail 返回的 spans 和 task 都包含 fact_id。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-detail-task", now)
        _insert_fact(conn, "fact-detail-llm", now)
        _insert_perf_signal(conn, signal_id="perf-s2d-task", fact_id="fact-detail-task", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-s2d", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-s2d-llm", fact_id="fact-detail-llm", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="ok",
                           trace_id="trace-s2d", occurred_at=now)
        detail = get_perf_task_detail(conn, "trace-s2d")
    # task span 包含 fact_id
    assert detail["task"]["fact_id"] == "fact-detail-task"
    # 每个 span 都包含 fact_id
    span_facts = {s["signal_id"]: s["fact_id"] for s in detail["spans"]}
    assert span_facts["perf-s2d-task"] == "fact-detail-task"
    assert span_facts["perf-s2d-llm"] == "fact-detail-llm"


def test_get_failure_timeline_returns_fact_id(tmp_path):
    """Slice 2: get_failure_timeline 返回的失败行包含 fact_id。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-fail-1", now)
        _insert_perf_signal(conn, signal_id="perf-s2f-err", fact_id="fact-fail-1", span_id="span-err",
                           span_type="llm_call", duration_ms=200, status="error",
                           trace_id="trace-s2f", occurred_at=now)
        failures = get_failure_timeline(conn, window="24h")
    assert len(failures) >= 1
    fail = next(f for f in failures if f["signal_id"] == "perf-s2f-err")
    assert fail["fact_id"] == "fact-fail-1"


# ---------- Slice 5/6: task_error 字段 + context_events 失败上下文 ----------

def test_get_perf_tasks_returns_task_error(tmp_path):
    """Slice 5: get_perf_tasks 返回 task_error 字段（取 task span 的 error）。

    前端用 task_error 区分"已中断"（interrupted/cancelled）与"失败"（其他 error），
    避免把用户主动中断误判为系统失败。
    """
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-task-err", now)
        _insert_perf_signal(conn, signal_id="perf-s5-task", fact_id="fact-task-err", span_id="trace-root",
                           span_type="task", duration_ms=500, status="error",
                           trace_id="trace-s5", occurred_at=now)
        # 修改 perf_signals.error 为 interrupted（_insert_perf_signal 默认 error=''）
        conn.execute(
            "update perf_signals set error='interrupted' where signal_id='perf-s5-task'"
        )
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    assert tasks["trace-s5"]["task_error"] == "interrupted"
    assert tasks["trace-s5"]["task_status"] == "error"


# ---------- _latency_stats: duration_ms=0 过滤 ----------

class _FakeRow:
    """模拟 sqlite3.Row 的字典式访问，用于 _latency_stats 单元测试。"""
    def __init__(self, duration_ms: int, ttft_ms: int = 0, status: str = "ok", tps: float = 0.0):
        self._data = {"duration_ms": duration_ms, "ttft_ms": ttft_ms, "tps": tps, "status": status}

    def __getitem__(self, key):
        return self._data[key]


def _make_row(duration_ms: int, ttft_ms: int = 0, status: str = "ok", tps: float = 0.0) -> _FakeRow:
    """构造最小 perf_signal row 用于 _latency_stats 测试。"""
    return _FakeRow(duration_ms=duration_ms, ttft_ms=ttft_ms, status=status, tps=tps)


def test_latency_stats_filters_zero_duration_from_percentiles():
    """duration_ms=0 的行不参与百分位/avg/min/max，但 sample_count 统计所有行。

    场景：codex llm_call span duration_ms=0（无 generation duration 字段），
    不应把 0 算进 P50/avg 等统计，否则会拉低指标。
    """
    rows = [
        _make_row(duration_ms=0, ttft_ms=500),   # llm_call span: duration=0, ttft=500
        _make_row(duration_ms=0, ttft_ms=600),   # llm_call span: duration=0, ttft=600
        _make_row(duration_ms=1000, ttft_ms=0),  # task span: duration=1000, ttft=0
    ]
    stats = _latency_stats(rows)
    # sample_count 统计所有行（包括 duration_ms=0）
    assert stats["sample_count"] == 3
    # duration 统计只算 duration_ms>0 的行（只有 1 条 1000ms）
    # n<20 时百分位返回 0，但 avg/min/max 应反映真实值
    assert stats["duration_avg_ms"] == 1000
    assert stats["duration_min_ms"] == 1000
    assert stats["duration_max_ms"] == 1000
    # ttft 统计只算 ttft_ms>0 的行（2 条：500, 600）
    assert stats["ttft_avg_ms"] == 550


def test_latency_stats_all_zero_duration_returns_zero_stats():
    """所有行 duration_ms=0 时，duration 相关统计全为 0（不崩溃）。"""
    rows = [
        _make_row(duration_ms=0, ttft_ms=500),
        _make_row(duration_ms=0, ttft_ms=600),
    ]
    stats = _latency_stats(rows)
    assert stats["sample_count"] == 2
    assert stats["duration_avg_ms"] == 0
    assert stats["duration_min_ms"] == 0
    assert stats["duration_max_ms"] == 0
    assert stats["duration_p50_ms"] == 0
    # ttft 仍有值
    assert stats["ttft_avg_ms"] == 550


def test_get_perf_tasks_task_error_falls_back_to_child(tmp_path):
    """Slice 5: task span 无 error 但子 span 有 error 时，task_error 回退到子 span error。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-s5b", now)
        _insert_perf_signal(conn, signal_id="perf-s5b-task", fact_id="fact-s5b", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-s5b", occurred_at=now)
        _insert_perf_signal(conn, signal_id="perf-s5b-llm-err", fact_id="fact-s5b", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="error",
                           trace_id="trace-s5b", occurred_at=now)
        conn.execute(
            "update perf_signals set error='timeout' where signal_id='perf-s5b-llm-err'"
        )
        result = get_perf_tasks(conn, window="24h", page=1, page_size=10)
    tasks = {t["trace_id"]: t for t in result["tasks"]}
    # task span 自身 error='' → 回退到子 span error='timeout'
    assert tasks["trace-s5b"]["task_error"] == "timeout"


def test_get_perf_task_detail_returns_context_events(tmp_path):
    """Slice 6: get_perf_task_detail 返回 context_events（同会话的 risk/error facts）。

    场景对应 trace 019f7472：task span interrupted（用户中断），会话内有 risk fact
    （文件变更）。context_events 帮助用户在抽屉内理解"中断前发生了什么"。
    """
    task_time = "2026-07-18T09:01:03+00:00"
    risk_time = "2026-07-18T09:00:32+00:00"  # 比 task 早 31 秒（上一个 turn 的文件变更）
    with connect(tmp_path / "observer.sqlite") as conn:
        # task span 的 fact
        _insert_fact(conn, "fact-task-ce", task_time, conversation_ref="conv-ce")
        _insert_perf_signal(conn, signal_id="perf-ce-task", fact_id="fact-task-ce", span_id="trace-root",
                           span_type="task", duration_ms=145216, status="error",
                           trace_id="trace-ce", conversation_ref="conv-ce", occurred_at=task_time)
        conn.execute(
            "update perf_signals set error='interrupted' where signal_id='perf-ce-task'"
        )
        # 同会话的 risk fact（文件变更，发生在 task 之前）
        _insert_fact(conn, "fact-risk-ce", risk_time, fact_type="risk",
                     category="file_change", summary="Agent 修改了 3 个工作区文件",
                     conversation_ref="conv-ce")
        detail = get_perf_task_detail(conn, "trace-ce")
    assert detail is not None
    # context_events 包含同会话的 risk fact
    assert len(detail["context_events"]) == 1
    event = detail["context_events"][0]
    assert event["fact_id"] == "fact-risk-ce"
    assert event["fact_type"] == "risk"
    assert event["category"] == "file_change"
    assert event["summary"] == "Agent 修改了 3 个工作区文件"
    # task span 的 error 仍保留
    assert detail["task"]["error"] == "interrupted"


def test_get_perf_task_detail_context_events_excludes_other_conversations(tmp_path):
    """Slice 6: context_events 只返回同一会话的 facts，不混入其他会话。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-task-conv1", now, conversation_ref="conv-1")
        _insert_perf_signal(conn, signal_id="perf-conv1-task", fact_id="fact-task-conv1", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-conv1", conversation_ref="conv-1", occurred_at=now)
        # 同会话的 risk fact
        _insert_fact(conn, "fact-risk-conv1", now, fact_type="risk",
                     category="file_change", summary="conv-1 risk",
                     conversation_ref="conv-1")
        # 不同会话的 risk fact（不应出现在 trace-conv1 的 context_events 中）
        _insert_fact(conn, "fact-risk-conv2", now, fact_type="risk",
                     category="file_change", summary="conv-2 risk",
                     conversation_ref="conv-2")
        detail = get_perf_task_detail(conn, "trace-conv1")
    assert detail is not None
    assert len(detail["context_events"]) == 1
    assert detail["context_events"][0]["fact_id"] == "fact-risk-conv1"


def test_get_perf_task_detail_context_events_empty_when_no_risk(tmp_path):
    """Slice 6: 会话内无 risk/error fact 时 context_events 为空数组。"""
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-no-risk", now, conversation_ref="conv-clean")
        _insert_perf_signal(conn, signal_id="perf-clean-task", fact_id="fact-no-risk", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-clean", conversation_ref="conv-clean", occurred_at=now)
        detail = get_perf_task_detail(conn, "trace-clean")
    assert detail is not None
    assert detail["context_events"] == []


def test_get_perf_task_detail_task_error_rolled_up_from_child(tmp_path):
    """P1-1: task span 自身 error 为空但子 span interrupted 时，detail.task_error 回退到子 span error。

    场景：用户在子调用期间中断。task span 状态 ok/error=''，子 llm_call span 状态 error/interrupted。
    修复前：抽屉元数据用 detail.task.error='' → perfStatusLabel('error','') = "失败"（与列表不一致）。
    修复后：抽屉用 detail.task_error='interrupted' → perfStatusLabel('error','interrupted') = "已中断"。
    """
    now = _now()
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_fact(conn, "fact-p11-task", now)
        _insert_fact(conn, "fact-p11-llm", now)
        # task span 自身状态 ok，error 为空
        _insert_perf_signal(conn, signal_id="perf-p11-task", fact_id="fact-p11-task", span_id="trace-root",
                           span_type="task", duration_ms=500, status="ok",
                           trace_id="trace-p11", occurred_at=now)
        # 子 llm_call span 状态 error，error=interrupted
        _insert_perf_signal(conn, signal_id="perf-p11-llm", fact_id="fact-p11-llm", span_id="span-llm",
                           span_type="llm_call", duration_ms=100, status="error",
                           trace_id="trace-p11", occurred_at=now)
        conn.execute(
            "update perf_signals set error='interrupted' where signal_id='perf-p11-llm'"
        )
        detail = get_perf_task_detail(conn, "trace-p11")
    assert detail is not None
    # task span 自身 error 仍为空
    assert detail["task"]["error"] == ""
    assert detail["task"]["status"] == "ok"
    # rolled-up task_error 回退到子 span error
    assert detail["task_error"] == "interrupted"
    assert detail["task_status"] == "error"