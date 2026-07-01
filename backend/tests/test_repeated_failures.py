from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.behavior_signals.service import rebuild_signals, list_signals
from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.processing.jobs import run_next_job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmpdb():
    path = Path(tempfile.mktemp(suffix=".sqlite"))
    yield path
    # Close any lingering connections on Windows
    import gc
    gc.collect()
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


def _ingest(conn: sqlite3.Connection, items: list[dict]) -> None:
    batch_id = f"batch-{items[0]['source_event_id']}"
    ingest_telemetry(
        conn,
        {
            "batch_id": batch_id,
            "protocol_version": "agent-observer-telemetry/v3",
            "agent_version": "0.3.0",
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


def _make_item(
    event_id: str,
    category: str,
    conversation_ref: str = "conversation-1",
    tool_name: str = "exec_command",
    exit_code: int = 1,
    command: str = "npm test",
    signature_suffix: str = "",
) -> dict:
    return {
        "source_event_id": event_id,
        "fact_type": "error",
        "category": category,
        "quality": "high",
        "severity": "high",
        "summary": f"{category}: {tool_name} exit_code={exit_code}",
        "occurred_at": "2026-06-18T10:00:00+00:00",
        "span": f"event:{event_id}",
        "raw_hash": f"hash-{event_id}",
        "source_refs": {
            "conversation_ref": conversation_ref,
            "session_ref": "session-1",
            "workspace_id": "codex:test",
            "workspace_path": "D:/workspace/test",
            "agent_type": "codex",
        },
        "source_specific": {"event_type": "tool_result"},
        "projection": {
            "tool_name": tool_name,
            "exit_code": exit_code,
            "command": command,
            "command_excerpt": command,
        },
        "error_signature": {
            "signature_key": f"tool_execution_failure:exec_command:cmd-{signature_suffix or event_id}:{exit_code}",
            "category": category,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_three_failures_trigger_repeated_tool_failure_signal(tmpdb):
    """3 failures with same signature in same conversation -> signal created."""
    items = [_make_item(f"fail-{i}", "tool_execution_failure", signature_suffix="abc") for i in range(3)]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "repeated_tool_failure"]
    assert len(signals) == 1
    assert signals[0]["occurrence_count"] == 3
    assert signals[0]["priority_score"] == 80
    assert "重复犯错" in signals[0]["title"]


def test_two_failures_do_not_trigger(tmpdb):
    """2 failures with same signature -> no repeated_tool_failure signal."""
    items = [_make_item(f"fail-{i}", "tool_execution_failure", signature_suffix="xyz") for i in range(2)]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "repeated_tool_failure"]
    assert len(signals) == 0


def test_accepted_risk_excludes_from_repeated_detection(tmpdb):
    """Signatures with accepted_risk risk_signal are excluded."""
    items = [_make_item(f"fail-{i}", "tool_execution_failure", signature_suffix="risk") for i in range(3)]
    with connect(tmpdb) as conn:
        _ingest(conn, items)

        # Get the actual signature_key used by these items
        sig_row = conn.execute(
            "select signature_key from error_signatures where category = 'tool_execution_failure' limit 1"
        ).fetchone()
        sig_key = sig_row["signature_key"] if sig_row else ""

        # Mark the underlying facts as accepted_risk BEFORE rebuilding signals
        if sig_key:
            conn.execute(
                """
                insert into risk_signals (signal_id, fact_id, risk_type, severity, object_type)
                select 'ar:' || esf.fact_id, esf.fact_id, 'accepted_risk', 'low', 'unknown'
                from error_signature_facts esf
                where esf.signature_key = ?
                """,
                (sig_key,),
            )
            conn.commit()

        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "repeated_tool_failure"]
    assert len(signals) == 0


def test_different_conversations_count_separately(tmpdb):
    """Same signature across 2 conversations, 3 each -> 2 signals."""
    items = [
        _make_item(f"fail-{i}-a", "tool_execution_failure", conversation_ref="conv-a", signature_suffix="sep")
        for i in range(3)
    ] + [
        _make_item(f"fail-{i}-b", "tool_execution_failure", conversation_ref="conv-b", signature_suffix="sep")
        for i in range(3)
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "repeated_tool_failure"]
    assert len(signals) == 2
    conv_refs = {s["affected_scope"]["conversation_ref"] for s in signals}
    assert conv_refs == {"conv-a", "conv-b"}


def test_signal_contains_occurrence_count(tmpdb):
    """Signal payload includes occurrence_count field."""
    items = [_make_item(f"fail-{i}", "tool_execution_failure", signature_suffix="count") for i in range(5)]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "repeated_tool_failure"]
    assert len(signals) == 1
    assert signals[0]["affected_scope"]["occurrence_count"] == 5


def test_workflow_gate_blocked_excluded(tmpdb):
    """Failures classified as workflow_gate_blocked should not trigger."""
    items = [_make_item(f"fail-{i}", "tool_execution_failure", signature_suffix="gate") for i in range(3)]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        # Insert a risk_signal marking the facts as workflow_gate_blocked
        result = rebuild_signals(conn, reason="test")
        exec_signals = [s for s in result["signals"] if s["signal_kind"] == "tool_execution_failure"]
        if exec_signals:
            sig = exec_signals[0]
            # We need to mark some facts as workflow_gate_blocked in risk_signals
            # The simplest way is to insert risk_signals entries
            conn.execute(
                """
                insert into risk_signals (signal_id, fact_id, risk_type, severity, object_type)
                select 'rg:' || substr(fact_id, 1, 8), fact_id, 'workflow_gate_blocked', 'low', 'unknown'
                from error_signature_facts
                where signature_key = (select signature_key from behavior_signals where signal_id = ? limit 1)
                """,
                (sig["signal_id"],),
            )
            conn.commit()
            result2 = rebuild_signals(conn, reason="test2")

        signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "repeated_tool_failure"]
        assert len(signals) == 0
