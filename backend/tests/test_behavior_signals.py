from __future__ import annotations

import json

from app.behavior_signals.service import get_signal_detail, handle_signal, list_signals, rebuild_signals
from app.db.connection import connect
from app.evidence_enrichment.service import get_enrichment_availability, request_enrichment
from app.ingest.service import ingest_telemetry
from app.processing.jobs import run_next_job
from source_payloads import default_versions


def _base_item(event_id: str, category: str, fact_type: str = "risk") -> dict:
    return {
        "source_event_id": event_id,
        "fact_type": fact_type,
        "category": category,
        "quality": "high",
        "severity": "high" if category in {"tool_execution_failure", "workflow_step_failure", "workflow_step_timeout"} else "medium",
        "summary": f"{category} {event_id}",
        "occurred_at": "2026-06-18T10:00:00+00:00",
        "span": f"event:{event_id}",
        "raw_hash": f"hash-{event_id}",
        "source_refs": {"conversation_ref": "conversation-1"},
        "source_specific": {"event_type": "tool_result"},
    }


def _with_workspace(item: dict, label: str, path: str = "D:/workspace/test-project-a") -> dict:
    refs = dict(item.get("source_refs") or {})
    refs.update(
        {
            "workspace_id": f"codex:{label.lower().replace(' ', '-')}",
            "workspace_path": path,
            "workspace_label": label,
            "workspace_alias_source": "codex_global_state",
            "workspace_confidence": "high",
            "agent_type": "codex",
        }
    )
    item["source_refs"] = refs
    return item


def _ingest(conn, items: list[dict]) -> None:
    ingest_telemetry(
        conn,
        {
            "batch_id": f"batch-{items[0]['source_event_id']}",
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


def test_tool_execution_failure_is_explainable_signal(tmp_path):
    prompt = _base_item("prompt-1", "agent_prompt", "event")
    prompt["source_refs"] = {"conversation_ref": "conversation-1", "session_title": "tool-failure-context"}
    prompt["projection"] = {"role": "user", "prompt_text": "fix tool failure"}
    prompt["raw_content"] = {"text": "fix tool failure"}
    item = _base_item("tool-failure-1", "tool_execution_failure", "error")
    item.update(
        {
            "summary": "function_call_output failed with exit_code=1",
            "projection": {
                "tool_name": "exec_command",
                "exit_code": 1,
                "command": "cmd /c start-server.cmd",
                "command_excerpt": "cmd /c start-server.cmd",
                "command_category": "shell",
                "error_excerpt": "Port 8765 is already in use.",
            },
            "error_signature": {"signature_key": "tool_execution_failure:exec_command:abc:1", "category": "tool_execution_failure"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [prompt, item])
        result = rebuild_signals(conn, reason="test")
        queue = list_signals(conn)
        signal = next(item for item in queue["signals"] if item["signal_kind"] == "tool_execution_failure")
        detail = get_signal_detail(conn, signal["signal_id"])

    assert result["updated"] == 1
    assert signal["title"] == "本会话 1 次 exec_command 执行失败，退出码 1"
    assert detail["evidence_groups"][0]["group_type"] == "failure"
    assert detail["evidence_groups"][0]["title"] == "命中事件"
    assert detail["evidence_groups"][0]["items"][0]["tool_context"]["command"] == "cmd /c start-server.cmd"
    assert detail["evidence_groups"][0]["items"][0]["tool_context"]["error_excerpt"] == "Port 8765 is already in use."
    assert detail["linked_conversations"][0]["conversation_ref"] == "conversation-1"
    assert detail["linked_conversations"][0]["session_title"] == "tool-failure-context"
    assert detail["linked_conversations"][0]["matched_fact_ids"] == [item["source_event_id"]]


def test_tool_execution_failures_aggregate_by_conversation_tool_and_exit_code(tmp_path):
    first = _base_item("tool-failure-a", "tool_execution_failure", "error")
    first["source_refs"] = {"conversation_ref": "conversation-1", "session_title": "story-definition-analysis"}
    first.update(
        {
            "summary": "工具执行失败：npm test，exit_code=1。",
            "projection": {
                "tool_name": "exec_command",
                "exit_code": 1,
                "command": "npm test",
                "command_excerpt": "npm test",
                "command_category": "test",
                "error_excerpt": "1 failed",
            },
            "error_signature": {"signature_key": "tool_execution_failure:exec_command:cmd-a:1", "category": "tool_execution_failure"},
        }
    )
    second = _base_item("tool-failure-b", "tool_execution_failure", "error")
    second["source_refs"] = {"conversation_ref": "conversation-1", "session_title": "story-definition-analysis"}
    second["occurred_at"] = "2026-06-18T11:00:00+00:00"  # 比 first 晚 → 详情按最新在前展示
    second.update(
        {
            "summary": "工具执行失败：python -m pytest，exit_code=1。",
            "projection": {
                "tool_name": "exec_command",
                "exit_code": 1,
                "command": "python -m pytest",
                "command_excerpt": "python -m pytest",
                "command_category": "test",
                "error_excerpt": "2 failed",
            },
            "error_signature": {"signature_key": "tool_execution_failure:exec_command:cmd-b:1", "category": "tool_execution_failure"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [first, second])
        signals = [item for item in list_signals(conn, window="all")["signals"] if item["signal_kind"] == "tool_execution_failure"]
        detail = get_signal_detail(conn, signals[0]["signal_id"])

    assert len(signals) == 1
    assert signals[0]["title"] == "本会话 2 次 exec_command 执行失败，退出码 1"
    assert signals[0]["occurrence_count"] == 2
    assert [group["group_type"] for group in detail["evidence_groups"]] == ["failure"]
    assert detail["linked_conversations"][0]["session_title"] == "story-definition-analysis"
    # 详情命中事件按最新在前展示（second 更晚，故 python -m pytest 在前）
    assert [item["tool_context"]["command"] for item in detail["evidence_groups"][0]["items"]] == ["python -m pytest", "npm test"]


def test_object_group_summary_is_time_range_not_count():
    # 回归保护：object_group 的 summary 是时间范围，不再是"N 条命中"（与 count badge 重复）。
    from app.behavior_signals.helpers import _time_range_label

    assert _time_range_label([
        {"occurred_at": "2026-04-08T11:00:00+00:00"},
        {"occurred_at": "2026-07-05T10:00:00+00:00"},
    ]) == "2026-04-08 ~ 2026-07-05"
    assert _time_range_label([{"occurred_at": "2026-07-05T10:00:00+00:00"}]) == "2026-07-05"
    assert _time_range_label([]) == ""
    assert _time_range_label([{"occurred_at": None}]) == ""


def test_signals_expose_and_filter_workspace_scope(tmp_path):
    item = _base_item("tool-failure-workspace", "tool_execution_failure", "error")
    item.update(
        {
            "summary": "function_call_output failed with exit_code=1",
            "projection": {"tool_name": "exec_command", "exit_code": 1},
            "error_signature": {"signature_key": "tool_execution_failure:workspace:exit:1", "category": "tool_execution_failure"},
        }
    )
    _with_workspace(item, "Test Project A")
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [item])
        queue = list_signals(conn, window="all", workspace_query="test")
        detail = get_signal_detail(conn, queue["signals"][0]["signal_id"])

    assert queue["total"] == 1
    assert queue["signals"][0]["workspace_summary"]["mode"] == "single"
    assert queue["signals"][0]["workspace_summary"]["label"] == "Test Project A"
    assert detail["workspace_refs"][0]["workspace_label"] == "Test Project A"


def test_signals_summarize_multiple_workspaces_and_filter_by_any_workspace(tmp_path):
    first = _base_item("tool-failure-workspace-a", "tool_execution_failure", "error")
    first.update(
        {
            "projection": {"tool_name": "exec_command", "exit_code": 1},
            "error_signature": {"signature_key": "tool_execution_failure:multi:exit:1", "category": "tool_execution_failure"},
        }
    )
    _with_workspace(first, "Test Project A", "D:/workspace/test-project-a")
    second = _base_item("tool-failure-workspace-b", "tool_execution_failure", "error")
    second.update(
        {
            "projection": {"tool_name": "exec_command", "exit_code": 1},
            "error_signature": {"signature_key": "tool_execution_failure:multi:exit:1", "category": "tool_execution_failure"},
        }
    )
    _with_workspace(second, "Test Project B", "D:/workspace/test-project-b")
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [first, second])
        queue = list_signals(conn, window="all", workspace_query="project-b")

    assert queue["total"] == 1
    assert queue["signals"][0]["workspace_summary"] == {"mode": "single", "label": "Test Project B", "count": 1}


def test_usage_events_do_not_generate_behavior_signals(tmp_path):
    usage = _base_item("usage-1", "usage", "usage")
    usage.update({"projection": {"activity_tag": "codex_turn", "units": 100}, "usage": {"units": 100, "activity_tag": "codex_turn"}})
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [usage])
        queue = list_signals(conn)

    assert queue["signals"] == []


def test_change_volume_anomaly_groups_by_conversation(tmp_path):
    items = []
    for index in range(20):
        item = _base_item(f"workspace-{index}", "file_change")
        item.update(
            {
                "summary": f"workspace file changed src/file_{index}.py",
                "projection": {
                    "object_type": "workspace_file",
                    "changed_paths": [f"src/file_{index}.py"],
                    "file_count": 1,
                    "additions": 30,
                    "deletions": 0,
                },
                "risk": {"risk_type": "file_change", "severity": "medium", "object_type": "workspace_file"},
            }
        )
        items.append(item)
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, items)
        detail = next(item for item in list_signals(conn, window="all")["signals"] if item["signal_kind"] == "change_volume_anomaly")

    assert detail["affected_scope"]["file_count"] == 20


def test_change_volume_anomaly_skips_missing_conversation_ref(tmp_path):
    item = _base_item("workspace-no-conversation", "file_change")
    item["source_refs"] = {}
    item.update(
        {
            "summary": "workspace files changed without conversation",
            "projection": {"object_type": "workspace_file", "changed_paths": [f"src/file_{index}.py" for index in range(20)], "additions": 600},
            "risk": {"risk_type": "file_change", "severity": "medium", "object_type": "workspace_file"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [item])
        queue = list_signals(conn, window="all")

    assert all(signal["signal_kind"] != "change_volume_anomaly" for signal in queue["signals"])


def test_workflow_timeout_signal_is_actionable_and_enrichable(tmp_path):
    item = _base_item("workflow-timeout-1", "workflow_step_timeout", "error")
    item.update(
        {
            "summary": "Workflow 步骤超时：spec-driven / run_123",
            "projection": {
                "tool_name": "exec_command",
                "exit_code": 124,
                "workflow": "spec-driven",
                "run_id": "run_123",
                "command": "python scripts/ao.py spec-driven resume --run-id run_123",
                "command_fingerprint": "abc123",
                "wall_time_seconds": 600,
            },
            "error_signature": {"signature_key": "workflow_step_timeout:spec-driven:run_123:124", "category": "workflow_step_timeout"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [item])
        signal = next(item for item in list_signals(conn, window="all")["signals"] if item["signal_kind"] == "workflow_step_timeout")
        availability = get_enrichment_availability(conn, signal["signal_id"])

    assert "unknown" not in signal["title"]
    assert availability["capabilities"][0]["state"] == "queueable"


def test_key_file_change_detects_config_entry_paths(tmp_path):
    item = _base_item("key-file-1", "file_change")
    item.update(
        {
            "summary": "changed .gitignore",
            "projection": {"object_type": "configuration", "changed_paths": [".gitignore"]},
            "risk": {"risk_type": "file_change", "severity": "medium", "object_type": "configuration"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, [item])
        key_signal = next(item for item in list_signals(conn, window="all")["signals"] if item["signal_kind"] == "key_file_change")

    assert key_signal["affected_scope"]["key_file_category"] == "项目忽略规则"


def test_signal_decision_and_enrichment_use_signal_id(tmp_path):
    item = _base_item("tool-failure-2", "tool_execution_failure", "error")
    item.update(
        {
            "projection": {"tool_name": "exec_command", "exit_code": 1},
            "error_signature": {"signature_key": "tool_execution_failure:exec:exit:1", "category": "tool_execution_failure"},
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


def test_destructive_operation_groups_by_conversation(tmp_path):
    """破坏性操作按会话聚合：不同会话生成不同信号，同一会话内多次操作合并为一条。"""
    items_a = []
    for index in range(3):
        item = _base_item(f"destruct-a-{index}", "destructive_operation")
        item["source_refs"] = {"conversation_ref": "conv-destruct-a"}
        item.update(
            {
                "summary": f"rm -rf /tmp/{index}",
                "risk": {"risk_type": "destructive_operation", "severity": "high"},
            }
        )
        items_a.append(item)
    item_b = _base_item("destruct-b-0", "destructive_operation")
    item_b["source_refs"] = {"conversation_ref": "conv-destruct-b"}
    item_b.update(
        {
            "summary": "chmod 777 /etc/passwd",
            "risk": {"risk_type": "destructive_operation", "severity": "high"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, items_a + [item_b])
        rebuild_signals(conn, reason="test")
        queue = list_signals(conn, window="all")
        destructive_signals = [s for s in queue["signals"] if s["signal_kind"] == "destructive_operation_attempt"]

    assert len(destructive_signals) == 2
    scopes = {s["affected_scope"]["conversation_ref"] for s in destructive_signals}
    assert scopes == {"conv-destruct-a", "conv-destruct-b"}
    conv_a_signal = next(s for s in destructive_signals if s["affected_scope"]["conversation_ref"] == "conv-destruct-a")
    assert conv_a_signal["affected_scope"]["operation_count"] == 3
    assert conv_a_signal["severity"] == "high"


def test_destructive_operation_legacy_scope_id_returns_empty(tmp_path):
    """旧格式 scope_id='destructive_operation'（无冒号）应返回空列表，不静默失败。"""
    from app.behavior_signals.service import _risk_builder

    with connect(tmp_path / "observer.sqlite") as conn:
        result = _risk_builder(conn, "test", "destructive_operation")

    assert result == []


def test_destructive_operation_per_conversation_scope_id(tmp_path):
    """新格式 scope_id='destructive_operation:{conv}' 应只处理指定会话。"""
    from app.behavior_signals.service import _risk_builder

    items_a = []
    for index in range(2):
        item = _base_item(f"destruct-scope-a-{index}", "destructive_operation")
        item["source_refs"] = {"conversation_ref": "conv-scope-a"}
        item.update(
            {
                "summary": f"rm -rf /tmp/{index}",
                "risk": {"risk_type": "destructive_operation", "severity": "high"},
            }
        )
        items_a.append(item)
    item_b = _base_item("destruct-scope-b-0", "destructive_operation")
    item_b["source_refs"] = {"conversation_ref": "conv-scope-b"}
    item_b.update(
        {
            "summary": "rm -rf /tmp/other",
            "risk": {"risk_type": "destructive_operation", "severity": "high"},
        }
    )
    with connect(tmp_path / "observer.sqlite") as conn:
        _ingest(conn, items_a + [item_b])
        result = _risk_builder(conn, "test", "destructive_operation:conv-scope-a")

    assert len(result) == 1
    assert result[0]["affected_scope"]["conversation_ref"] == "conv-scope-a"
    assert result[0]["affected_scope"]["operation_count"] == 2
