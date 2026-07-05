from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.behavior_signals.service import rebuild_signals, list_signals
from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.processing.jobs import run_next_job
from source_payloads import default_versions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmpdb():
    path = Path(tempfile.mktemp(suffix=".sqlite"))
    yield path
    import gc
    gc.collect()
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


def _ingest(conn, items: list[dict]) -> None:
    batch_id = f"batch-{items[0]['source_event_id']}"
    ingest_telemetry(
        conn,
        {
            "batch_id": batch_id,
            **default_versions(),
            "collector_id": "collector-codex",
            "source": "codex",
            "source_id": "codex-local",
            "agent_type": "codex",
            "source_kind": "codex_local",
            "cursor": "cursor",
            "items": items,
        },
    )
    while run_next_job(conn, reason="test")["processed"]:
        pass


def _content_fact(
    event_id: str,
    fact_type: str = "content",
    category: str = "agent_prompt",
    conversation_ref: str = "conv-1",
    occurred_at: str = "2026-06-18T10:00:00+00:00",
    source_specific: dict | None = None,
    is_final: bool = False,
) -> dict:
    spec = source_specific or {}
    if is_final:
        spec["is_final"] = True
    return {
        "source_event_id": event_id,
        "fact_type": fact_type,
        "category": category,
        "quality": "high",
        "severity": "low",
        "summary": f"{category} event",
        "occurred_at": occurred_at,
        "span": f"event:{event_id}",
        "raw_hash": f"hash-{event_id}",
        "raw_content": json.dumps({"event_id": event_id, "type": category}),
        "source_refs": {
            "conversation_ref": conversation_ref,
            "session_ref": "session-1",
            "workspace_id": "test",
            "workspace_path": "/tmp/test",
            "agent_type": "codex",
        },
        "source_specific_json": json.dumps(spec) if spec else None,
        "projection": {
            "tool_name": category,
        },
    }


def _tool_fact(
    event_id: str,
    category: str = "function_call",
    conversation_ref: str = "conv-1",
    occurred_at: str = "2026-06-18T10:00:00+00:00",
    tool_name: str = "exec_command",
    source_specific: dict | None = None,
) -> dict:
    spec = source_specific or {}
    return {
        "source_event_id": event_id,
        "fact_type": "tool_result",
        "category": category,
        "quality": "high",
        "severity": "low",
        "summary": f"{category}: {tool_name}",
        "occurred_at": occurred_at,
        "span": f"event:{event_id}",
        "raw_hash": f"hash-{event_id}",
        "raw_content": json.dumps({"event_id": event_id, "type": category, "tool": tool_name}),
        "source_refs": {
            "conversation_ref": conversation_ref,
            "session_ref": "session-1",
            "workspace_id": "test",
            "workspace_path": "/tmp/test",
            "agent_type": "codex",
        },
        "source_specific_json": json.dumps(spec) if spec else None,
        "projection": {
            "tool_name": tool_name,
        },
    }


# ---------------------------------------------------------------------------
# Unit tests: 10-minute window calculation + content event filtering
# ---------------------------------------------------------------------------

def test_window_calculation_no_content_but_tools_stuck(tmpdb):
    """No content events, only tool calls spanning 10+ minutes -> signal created."""
    base = "2026-06-18T10:"
    items = [
        _tool_fact(f"tc-{i}", occurred_at=f"{base}{i:02d}:00+00:00")
        for i in range(15)  # 15 tool calls over 15 minutes
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 1
    assert signals[0]["priority_score"] == 75
    assert "卡循环" in signals[0]["title"]
    assert signals[0]["affected_scope"]["tool_call_count"] == 15


def test_content_events_prevent_stuck_signal(tmpdb):
    """Regular conversation with content events and tool calls -> no signal."""
    items = []
    for i in range(5):
        items.append(_content_fact(f"cp-{i}", category="agent_prompt", occurred_at=f"2026-06-18T10:{i:02d}:00+00:00"))
        items.append(_content_fact(f"cr-{i}", category="agent_response", occurred_at=f"2026-06-18T10:{i+1:02d}:00+00:00"))
        items.append(_tool_fact(f"tc-{i}", occurred_at=f"2026-06-18T10:{i+1:02d}:30+00:00"))
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 0


def test_tail_tools_after_last_content_stuck(tmpdb):
    """3+ tool calls after the last content event -> signal created."""
    items = [
        _content_fact("cp-0", category="agent_prompt", occurred_at="2026-06-18T10:00:00+00:00"),
        _tool_fact("tc-1", occurred_at="2026-06-18T10:05:00+00:00"),
        _tool_fact("tc-2", occurred_at="2026-06-18T10:06:00+00:00"),
        _tool_fact("tc-3", occurred_at="2026-06-18T10:07:00+00:00"),
        _tool_fact("tc-4", occurred_at="2026-06-18T10:08:00+00:00"),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 1
    assert signals[0]["affected_scope"]["tool_call_count"] == 4


def test_gap_between_content_events_with_accumulated_tools(tmpdb):
    """10-min gap between content events with 3+ tool calls in gap -> signal."""
    items = [
        _content_fact("cp-0", category="agent_prompt", occurred_at="2026-06-18T10:00:00+00:00"),
        _tool_fact("tc-1", occurred_at="2026-06-18T10:05:00+00:00"),
        _tool_fact("tc-2", occurred_at="2026-06-18T10:06:00+00:00"),
        _tool_fact("tc-3", occurred_at="2026-06-18T10:07:00+00:00"),
        _content_fact("cp-1", category="agent_response", occurred_at="2026-06-18T10:15:00+00:00"),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 1


# ---------------------------------------------------------------------------
# Integration test: end-to-end loop-stuck fact pipeline
# ---------------------------------------------------------------------------

def test_integration_loop_stuck_signal_generated(tmpdb):
    """End-to-end: ingest facts with loop-stuck pattern, verify signal with correct structure."""
    items = [
        _content_fact("cp-0", category="agent_prompt", occurred_at="2026-06-18T10:00:00+00:00"),
        _tool_fact("tc-1", category="function_call", occurred_at="2026-06-18T10:05:00+00:00", tool_name="run_script"),
        _tool_fact("tc-2", category="function_call_output", occurred_at="2026-06-18T10:06:00+00:00", tool_name="run_script"),
        _tool_fact("tc-3", category="function_call", occurred_at="2026-06-18T10:07:00+00:00", tool_name="run_script"),
        _tool_fact("tc-4", category="function_call_output", occurred_at="2026-06-18T10:08:00+00:00", tool_name="run_script"),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 1
    sig = signals[0]
    assert sig["signal_kind"] == "agent_loop_stuck"
    assert sig["priority_score"] == 75
    assert sig["severity"] == "high"
    assert sig["confidence"] == "high"
    assert "卡循环" in sig["title"]
    assert sig["affected_scope"]["conversation_count"] == 1
    assert sig["affected_scope"]["tool_call_count"] == 4
    assert "run_script" in sig["affected_scope"]["tool_names"]


# ---------------------------------------------------------------------------
# Exclusion tests: normal end / idle conversation
# ---------------------------------------------------------------------------

def test_normal_end_excludes_stuck_signal(tmpdb):
    """Conversation ending with a final agent_response -> no signal."""
    items = [
        _content_fact("cp-0", category="agent_prompt", occurred_at="2026-06-18T10:00:00+00:00"),
        _tool_fact("tc-1", occurred_at="2026-06-18T10:05:00+00:00"),
        _tool_fact("tc-2", occurred_at="2026-06-18T10:06:00+00:00"),
        _tool_fact("tc-3", occurred_at="2026-06-18T10:07:00+00:00"),
        _content_fact(
            "cp-final",
            category="agent_response",
            occurred_at="2026-06-18T10:08:00+00:00",
            is_final=True,
        ),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 0


def test_idle_conversation_no_signal(tmpdb):
    """Conversation with no events at all -> no signal."""
    # Empty ingestion — no facts
    with connect(tmpdb) as conn:
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 0


def test_only_content_no_tools_no_signal(tmpdb):
    """Content events but no tool calls -> not a loop stuck scenario."""
    items = [
        _content_fact("cp-0", category="agent_prompt", occurred_at="2026-06-18T10:00:00+00:00"),
        _content_fact("cp-1", category="agent_response", occurred_at="2026-06-18T10:05:00+00:00"),
        _content_fact("cp-2", category="agent_reasoning", occurred_at="2026-06-18T10:10:00+00:00"),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 0


def test_less_than_3_tail_tools_no_signal(tmpdb):
    """Fewer than 3 tool calls after last content -> no signal."""
    items = [
        _content_fact("cp-0", category="agent_prompt", occurred_at="2026-06-18T10:00:00+00:00"),
        _tool_fact("tc-1", occurred_at="2026-06-18T10:05:00+00:00"),
        _tool_fact("tc-2", occurred_at="2026-06-18T10:06:00+00:00"),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 0


def test_short_tool_span_no_signal(tmpdb):
    """Tool calls spanning less than 10 minutes with only 2 events -> no signal."""
    items = [
        _tool_fact("tc-0", occurred_at="2026-06-18T10:00:00+00:00"),
        _tool_fact("tc-1", occurred_at="2026-06-18T10:05:00+00:00"),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "agent_loop_stuck"]
    assert len(signals) == 0
