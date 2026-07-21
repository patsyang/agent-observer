"""codex fact_mapper _perf_fact 拆分 llm_call span 的测试。

覆盖：
- _perf_fact 产出 task + llm_call 两个 span
- task span 的 ttft_ms=0（TTFT 迁移到 llm_call span）
- llm_call span 继承原 ttft_ms，parent_span_id 指向 task span
- summary/projection 保留原始 ttft_ms 值（不从 task span 字段取）
- _insert_perf_signals 的 upsert 行为：duplicate 分支重新上传时更新 task span ttft_ms=0
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.collector_client.fact_mapper import _perf_fact
from app.db.connection import connect
from app.ingest.service import _insert_perf_signals


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _make_common() -> dict:
    return {
        "source_event_id": "evt-test-1",
        "occurred_at": _now(),
        "span": "codex-session:test",
        "raw_hash": "hash-test",
        "source_refs": {"conversation_ref": "conv-test"},
        "source_specific": {"event_type": "task_complete", "source_template": "codex.local.sessions.v1"},
        "upload_raw": True,
    }


def _make_record(event_type: str = "task_complete", ttft_ms: int | None = 5678) -> dict:
    payload: dict = {
        "type": event_type,
        "turn_id": "turn-abc-123-def-456",
        "duration_ms": 456789,
        "completed_at": 1752834663,
    }
    if ttft_ms is not None:
        payload["time_to_first_token_ms"] = ttft_ms
    if event_type == "turn_aborted":
        payload["reason"] = "interrupted"
    return {
        "payload": payload,
        "timestamp": "2026-07-18T09:01:03+00:00",
    }


# ---------- _perf_fact: 拆分 llm_call span ----------

def test_perf_fact_produces_two_spans():
    """_perf_fact 应产出 task + llm_call 两个 span。"""
    fact = _perf_fact(_make_common(), _make_record("task_complete", ttft_ms=5678))
    spans = fact["perf_signals"]
    assert len(spans) == 2
    span_types = [s["span_type"] for s in spans]
    assert "task" in span_types
    assert "llm_call" in span_types


def test_perf_fact_task_span_ttft_is_zero():
    """task span 的 ttft_ms 应为 0（TTFT 迁移到 llm_call span）。"""
    fact = _perf_fact(_make_common(), _make_record("task_complete", ttft_ms=5678))
    task_span = next(s for s in fact["perf_signals"] if s["span_type"] == "task")
    assert task_span["ttft_ms"] == 0


def test_perf_fact_llm_call_span_inherits_ttft():
    """llm_call span 应继承原 ttft_ms，parent_span_id 指向 task span，duration_ms=0（无 generation duration 字段）。"""
    fact = _perf_fact(_make_common(), _make_record("task_complete", ttft_ms=5678))
    task_span = next(s for s in fact["perf_signals"] if s["span_type"] == "task")
    llm_span = next(s for s in fact["perf_signals"] if s["span_type"] == "llm_call")
    assert llm_span["ttft_ms"] == 5678
    assert llm_span["parent_span_id"] == task_span["span_id"]
    assert llm_span["span_name"] == "codex_generation"
    # duration_ms=0：codex turn 事件无 LLM generation duration 字段，不能把 turn duration 当 LLM duration
    assert llm_span["duration_ms"] == 0
    assert task_span["duration_ms"] > 0  # task span 保留 turn 总耗时


def test_perf_fact_llm_call_span_status_matches_task():
    """llm_call span 的 status/error 应与 task span 一致。"""
    # task_complete
    fact_ok = _perf_fact(_make_common(), _make_record("task_complete"))
    task_ok = next(s for s in fact_ok["perf_signals"] if s["span_type"] == "task")
    llm_ok = next(s for s in fact_ok["perf_signals"] if s["span_type"] == "llm_call")
    assert llm_ok["status"] == task_ok["status"] == "ok"
    assert llm_ok["error"] == task_ok["error"] == ""

    # turn_aborted
    fact_abort = _perf_fact(_make_common(), _make_record("turn_aborted"))
    task_abort = next(s for s in fact_abort["perf_signals"] if s["span_type"] == "task")
    llm_abort = next(s for s in fact_abort["perf_signals"] if s["span_type"] == "llm_call")
    assert llm_abort["status"] == task_abort["status"] == "error"
    assert llm_abort["error"] == task_abort["error"] == "interrupted"


def test_perf_fact_llm_call_span_ttft_zero_when_aborted():
    """turn_aborted 事件无 ttft_ms，llm_call span 的 ttft_ms 也应为 0。"""
    fact = _perf_fact(_make_common(), _make_record("turn_aborted", ttft_ms=None))
    llm_span = next(s for s in fact["perf_signals"] if s["span_type"] == "llm_call")
    assert llm_span["ttft_ms"] == 0


def test_perf_fact_summary_preserves_original_ttft():
    """summary 应保留原始 ttft_ms 值（用局部变量，不从 task span 字段取）。"""
    fact = _perf_fact(_make_common(), _make_record("task_complete", ttft_ms=5678))
    task_span = next(s for s in fact["perf_signals"] if s["span_type"] == "task")
    assert task_span["ttft_ms"] == 0
    # summary 仍显示原始 TTFT 值
    assert "TTFT 5678ms" in fact["summary"]


def test_perf_fact_projection_preserves_original_ttft():
    """projection 应保留原始 ttft_ms 值（作为事实记录，不随 span 拆分而变）。"""
    fact = _perf_fact(_make_common(), _make_record("task_complete", ttft_ms=5678))
    assert fact["projection"]["ttft_ms"] == 5678


def _insert_minimal_fact(conn, fact_id: str) -> None:
    """插入最小 observed_facts 行，满足 perf_signals 的 FK 约束。"""
    conn.execute(
        """
        insert into observed_facts (
          fact_id, source_event_id, batch_id, collector_id, source_id, source, agent_type, source_kind,
          fact_type, category, normalized_event_type, quality,
          severity, summary, occurred_at, promoted_to_signal, source_refs_json,
          source_specific_json, content_preview, raw_available, raw_status, conversation_ref,
          session_ref, source_event_type, source_path_hash, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '{}', '{}', '', 0, '', '', '', '', '', ?)
        """,
        (
            fact_id, fact_id, "batch-test", "collector-test", "src-test", "codex", "codex", "codex_local",
            "perf", "agent_turn_latency", "trace", "high",
            "low", "test fact", _now(),
            _now(),
        ),
    )


# ---------- _insert_perf_signals: upsert 行为（P0-2 回归） ----------

def test_insert_perf_signals_upsert_updates_task_span_ttft(tmp_path):
    """P0-2: duplicate 分支重新上传时，task span 的 ttft_ms 应被更新为 0。

    场景：旧版 collector 上传了 task span（ttft_ms=5678），
    新版 collector 重新上传同一 fact（task span ttft_ms=0 + 新增 llm_call span）。
    _insert_perf_signals 应 upsert，把 task span 的 ttft_ms 从 5678 更新为 0，
    避免 TTFT 在 task span 和 llm_call span 重复统计。
    """
    with connect(tmp_path / "observer.sqlite") as conn:
        fact_id = "fact-test-1"
        _insert_minimal_fact(conn, fact_id)
        # 旧版 collector 上传的 task span（ttft_ms=5678）
        old_item = {
            "occurred_at": _now(),
            "source_refs": {"conversation_ref": "conv-test"},
            "perf_signals": [
                {
                    "trace_id": "turn-abc",
                    "span_id": "task-turn-abc-123",
                    "span_type": "task",
                    "span_name": "codex_turn",
                    "duration_ms": 456789,
                    "ttft_ms": 5678,
                    "tps": 0.0,
                    "status": "ok",
                    "error": "",
                    "model": "",
                    "tool_name": "",
                    "occurred_at": _now(),
                }
            ],
        }
        _insert_perf_signals(conn, fact_id, old_item, agent_type="codex")
        old_row = conn.execute(
            "select ttft_ms from perf_signals where signal_id = ?",
            ("perf-fact-test-1-task-turn-abc-123",),
        ).fetchone()
        assert old_row["ttft_ms"] == 5678

        # 新版 collector 重新上传（task span ttft_ms=0 + llm_call span ttft_ms=5678）
        new_item = {
            "occurred_at": _now(),
            "source_refs": {"conversation_ref": "conv-test"},
            "perf_signals": [
                {
                    "trace_id": "turn-abc",
                    "span_id": "task-turn-abc-123",
                    "span_type": "task",
                    "span_name": "codex_turn",
                    "duration_ms": 456789,
                    "ttft_ms": 0,
                    "tps": 0.0,
                    "status": "ok",
                    "error": "",
                    "model": "",
                    "tool_name": "",
                    "occurred_at": _now(),
                },
                {
                    "trace_id": "turn-abc",
                    "span_id": "llm-turn-abc-123",
                    "parent_span_id": "task-turn-abc-123",
                    "span_type": "llm_call",
                    "span_name": "codex_generation",
                    "duration_ms": 456789,
                    "ttft_ms": 5678,
                    "tps": 0.0,
                    "status": "ok",
                    "error": "",
                    "model": "",
                    "tool_name": "",
                    "occurred_at": _now(),
                },
            ],
        }
        _insert_perf_signals(conn, fact_id, new_item, agent_type="codex")

        # task span 的 ttft_ms 应被 upsert 更新为 0
        task_row = conn.execute(
            "select ttft_ms from perf_signals where signal_id = ?",
            ("perf-fact-test-1-task-turn-abc-123",),
        ).fetchone()
        assert task_row["ttft_ms"] == 0, "task span ttft_ms 应被 upsert 更新为 0"

        # llm_call span 应被插入
        llm_row = conn.execute(
            "select ttft_ms from perf_signals where signal_id = ?",
            ("perf-fact-test-1-llm-turn-abc-123",),
        ).fetchone()
        assert llm_row is not None
        assert llm_row["ttft_ms"] == 5678