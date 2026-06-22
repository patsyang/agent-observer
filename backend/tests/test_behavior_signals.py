from __future__ import annotations

import json

from app.behavior_signals.service import get_signal_detail, handle_signal, list_signals, rebuild_signals
from app.db.connection import connect
from app.evidence_enrichment.service import get_enrichment_availability, request_enrichment
from app.ingest.service import ingest_telemetry


def _base_item(event_id: str, category: str, fact_type: str = "risk") -> dict:
    return {
        "source_event_id": event_id,
        "fact_type": fact_type,
        "category": category,
        "quality": "high",
        "severity": "high" if category == "codex_error" else "medium",
        "summary": f"{category} {event_id}",
        "occurred_at": "2026-06-18T10:00:00+00:00",
        "span": f"event:{event_id}",
        "raw_hash": f"hash-{event_id}",
        "source_refs": {"conversation_ref": "conversation-1"},
        "source_specific": {"codex_event_type": "tool_result"},
    }


def _ingest(conn, items: list[dict]) -> None:
    ingest_telemetry(
        conn,
        {
            "batch_id": f"batch-{items[0]['source_event_id']}",
            "protocol_version": "agent-observer-telemetry/v2",
            "agent_version": "0.2.0",
            "collector_id": "collector-codex",
            "source": "codex",
            "cursor": "cursor",
            "items": items,
        },
    )


def test_tool_failure_cluster_is_explainable_signal(tmp_path):
    item = _base_item("tool-failure-1", "codex_error", "error")
    item.update(
        {
            "summary": "function_call_output failed with exit_code=1",
            "projection": {"tool_name": "exec_command", "exit_code": 1},
            "error_signature": {"signature_key": "function_call_output:exec:exit:1", "category": "codex_error"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [item])
        result = rebuild_signals(conn, reason="test")
        queue = list_signals(conn)
        signal = next(item for item in queue["signals"] if item["signal_kind"] == "tool_failure_cluster")
        detail = get_signal_detail(conn, signal["signal_id"])

    assert result["updated"] == 1
    assert signal["title"].startswith("工具失败集中出现")
    assert detail["evidence_groups"][0]["group_type"] == "failure"
    assert detail["linked_conversations"][0]["conversation_ref"] == "conversation-1"


def test_usage_events_do_not_generate_behavior_signals(tmp_path):
    usage = _base_item("usage-1", "usage", "usage")
    usage.update({"projection": {"activity_tag": "codex_turn", "units": 100}, "usage": {"units": 100, "activity_tag": "codex_turn"}})
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [usage])
        queue = list_signals(conn)

    assert queue["signals"] == []


def test_workspace_change_burst_groups_by_conversation(tmp_path):
    items = []
    for index in range(20):
        item = _base_item(f"workspace-{index}", "high_risk_operation")
        item.update(
            {
                "summary": f"workspace file changed src/file_{index}.py",
                "projection": {"object_type": "workspace_file", "path": f"src/file_{index}.py"},
                "risk": {"risk_type": "high_risk_operation", "severity": "medium", "object_type": "workspace_file"},
            }
        )
        items.append(item)
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, items)
        detail = next(item for item in list_signals(conn, window="all")["signals"] if item["signal_kind"] == "workspace_change_burst")

    assert detail["affected_scope"]["operation_count"] == 20
    assert detail["affected_scope"]["file_count"] == 20


def test_key_file_change_detects_config_entry_paths(tmp_path):
    item = _base_item("key-file-1", "high_risk_operation")
    item.update(
        {
            "summary": "changed .gitignore",
            "projection": {"object_type": "configuration", "path": ".gitignore"},
            "risk": {"risk_type": "high_risk_operation", "severity": "medium", "object_type": "configuration"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [item])
        key_signal = next(item for item in list_signals(conn, window="all")["signals"] if item["signal_kind"] == "key_file_change")

    assert key_signal["affected_scope"]["key_file_category"] == "项目忽略规则"


def test_signal_decision_and_enrichment_use_signal_id(tmp_path):
    item = _base_item("tool-failure-2", "codex_error", "error")
    item.update(
        {
            "projection": {"tool_name": "exec_command", "exit_code": 1},
            "error_signature": {"signature_key": "function_call_output:exec:exit:1", "category": "codex_error"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [item])
        signal = list_signals(conn, window="all")["signals"][0]
        handled = handle_signal(conn, signal["signal_id"], "known_issue", "tracked")
        availability = get_enrichment_availability(conn, signal["signal_id"])
        job = request_enrichment(conn, signal["signal_id"], "codex_tool_failure_context")

    assert handled["decision_state"] == "handled"
    assert handled["conclusion_code"] == "known_issue"
    assert availability["signal_id"] == signal["signal_id"]
    assert job["command"]["signal_id"] == signal["signal_id"]
    assert "story_id" not in json.dumps(job)
