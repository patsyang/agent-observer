from __future__ import annotations

import json
import os
import time

from app.collector_client.telemetry import collect_facts


def _write_session(codex_home, name: str = "session-001.jsonl") -> None:
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-18T10:00:00+00:00",
            "type": "tool_result",
            "tool": "shell",
            "exit_code": 1,
            "phase": "run",
            "project": "agent-observer",
            "conversation_id": "conversation-001",
            "session_id": "session-001",
            "summary": "shell command failed while running tests",
        },
        {
            "timestamp": "2026-06-18T10:02:00+00:00",
            "type": "usage",
            "total_tokens": 180,
            "activity_tags": ["shell_debug", "test_run"],
            "conversation_id": "conversation-001",
            "session_id": "session-001",
            "project": "agent-observer",
        },
        {
            "timestamp": "2026-06-18T10:03:00+00:00",
            "type": "tool_call",
            "tool": "apply_patch",
            "operation": "delete",
            "path": "backend/app/policy.py",
            "conversation_id": "conversation-001",
            "session_id": "session-001",
            "project": "agent-observer",
        },
        {
            "timestamp": "2026-06-18T10:04:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "arguments": json.dumps({"command": "curl -H 'Authorization: Bearer abcdefghijklmnop' http://127.0.0.1"}),
            },
            "conversation_id": "conversation-001",
            "session_id": "session-001",
            "project": "agent-observer",
        },
        {
            "timestamp": "2026-06-18T10:05:00+00:00",
            "type": "message",
            "conversation_id": "conversation-001",
            "session_id": "session-001",
            "project": "agent-observer",
        },
    ]
    (sessions / name).write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def _write_real_shape_session(codex_home, name: str = "real-shape.jsonl") -> None:
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "timestamp": "2026-06-18T11:00:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "call_id": "call-real-001",
                "arguments": json.dumps({
                    "command": "python -m pytest backend/tests",
                    "workdir": "D:/workspace/agentic_factory/apps/agent-observer",
                    "timeout_ms": 120000,
                }),
            },
        },
        {
            "timestamp": "2026-06-18T11:01:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-real-001",
                "output": "Exit code: 1\nWall time: 1.0 seconds\nOutput omitted by fixture",
            },
        },
        {
            "timestamp": "2026-06-18T11:02:00+00:00",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 20, "total_tokens": 120},
                    "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 20, "total_tokens": 120},
                    "model_context_window": 258400,
                },
                "rate_limits": {},
            },
        },
        {
            "timestamp": "2026-06-18T11:03:00+00:00",
            "type": "event_msg",
            "payload": {
                "type": "patch_apply_end",
                "call_id": "call-real-002",
                "success": True,
                "status": "completed",
                "changes": {"backend/app/collector_client/telemetry.py": {"additions": 3, "deletions": 1}},
                "stdout": "not uploaded",
                "stderr": "",
            },
        },
        {
            "timestamp": "2026-06-18T11:03:10+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "call_id": "call-real-token-telemetry",
                "arguments": json.dumps({
                    "command": 'git commit -m "task-execution-state 与 token telemetry 契约"',
                    "workdir": "D:/workspace/agentic_factory/apps/agent-observer",
                }),
            },
        },
        {
            "timestamp": "2026-06-18T11:03:30+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "call_id": "call-real-003",
                "arguments": json.dumps({
                    "command": "Get-Content $env:USERPROFILE/.codex/auth.json",
                    "workdir": "D:/workspace/agentic_factory/apps/agent-observer",
                }),
            },
        },
        {
            "timestamp": "2026-06-18T11:04:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "请检查 Dashboard 为什么看不到原始 Prompt"}],
            },
        },
        {
            "timestamp": "2026-06-18T11:05:00+00:00",
            "type": "event_msg",
            "payload": {
                "type": "reasoning",
                "summary": "模型正在判断证据链刷新路径",
            },
        },
    ]
    (sessions / name).write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")


def test_codex_source_template_extracts_structured_facts_with_raw_content_by_default(tmp_path):
    codex_home = tmp_path / ".codex"
    _write_session(codex_home)

    facts = collect_facts(
        "collector-codex",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    categories = {fact["category"] for fact in facts}
    assert {"tool_execution_failure", "usage", "destructive_operation", "sensitive_content_exposure", "agent_response"} <= categories
    assert "uncategorized" not in categories
    assert any(fact.get("error_signature") for fact in facts if fact["category"] == "tool_execution_failure")
    assert any(fact.get("usage", {}).get("activity_tag") == "shell_debug" for fact in facts)
    assert any(fact.get("risk", {}).get("risk_type") == "destructive_operation" for fact in facts)
    sensitive_fact = next(fact for fact in facts if fact["category"] == "sensitive_content_exposure")
    assert sensitive_fact["projection"]["object_type"] == "credential"
    assert sensitive_fact["projection"]["sensitive_categories"] == ["token"]
    assert sensitive_fact["projection"]["sensitive_matches"][0]["match_type"] == "authorization_bearer"
    message_fact = next(fact for fact in facts if fact["category"] == "agent_response")
    assert message_fact["projection"]["role"] == "unknown"
    assert message_fact["projection"]["content_length"] == 0
    assert "raw_content" in message_fact
    assert all(fact["raw_hash"] for fact in facts)
    assert all(fact["source_refs"]["source_path_hash"] for fact in facts if fact["category"] != "collector_health")


def test_codex_source_template_uses_cursor_and_max_events(tmp_path):
    codex_home = tmp_path / ".codex"
    _write_session(codex_home)

    cursor = {"last_sequence": 0, "sources": {}}
    first = collect_facts(
        "collector-codex",
        1,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor=cursor,
    )
    second = collect_facts(
        "collector-codex",
        2,
        "safe_probe",
        codex_home=codex_home,
        max_events=20,
        cursor=cursor,
    )

    assert len([fact for fact in first if fact["category"] != "collector_health"]) == 2
    assert len([fact for fact in second if fact["category"] != "collector_health"]) == 3
    assert {fact["source_event_id"] for fact in first}.isdisjoint(
        {fact["source_event_id"] for fact in second if fact["category"] != "collector_health"}
    )


def test_codex_source_template_groups_records_without_conversation_id_by_session_file(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-18T10:00:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "输入内容"}],
            },
        },
        {
            "timestamp": "2026-06-18T10:01:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "输出内容"}],
            },
        },
        {
            "timestamp": "2026-06-18T10:02:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": "{}",
            },
        },
    ]
    (sessions / "session-without-conversation-id.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records),
        encoding="utf-8",
    )

    facts = collect_facts(
        "collector-codex",
        1,
        "safe_probe",
        codex_home=codex_home,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    refs = {
        fact["source_refs"]["conversation_ref"]
        for fact in facts
        if fact["category"] in {"agent_prompt", "agent_response", "tool_call"}
    }
    assert len(refs) == 1


def test_codex_source_template_prioritizes_recent_sessions_for_first_cycle(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    old_path = sessions / "old.jsonl"
    recent_path = sessions / "recent.jsonl"
    old_path.write_text(json.dumps({"type": "message", "conversation_id": "old"}) + "\n", encoding="utf-8")
    recent_path.write_text(json.dumps({"type": "message", "conversation_id": "recent"}) + "\n", encoding="utf-8")
    now = time.time()
    os.utime(old_path, (now - 120, now - 120))
    os.utime(recent_path, (now - 10, now - 10))

    facts = collect_facts(
        "collector-codex",
        1,
        "safe_probe",
        codex_home=codex_home,
        max_events=1,
        cursor={"last_sequence": 0, "sources": {}},
    )

    first_source_key = next(fact["source_refs"]["source_key"] for fact in facts if fact["category"] != "collector_health")
    assert first_source_key.endswith("recent.jsonl:00000001")


def test_codex_source_template_prioritizes_live_tail_when_history_cursor_is_behind(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    active_path = sessions / "active.jsonl"
    records = [
        {
            "timestamp": f"2026-06-18T11:{index:02d}:00+00:00",
            "type": "message",
            "conversation_id": f"conversation-{index}",
            "session_id": "session-active",
        }
        for index in range(20)
    ]
    active_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    now = time.time()
    os.utime(active_path, (now, now))

    cursor = {"last_sequence": 0, "sources": {}}
    collect_facts(
        "collector-codex",
        2,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor=cursor,
    )
    facts = collect_facts(
        "collector-codex",
        3,
        "safe_probe",
        codex_home=codex_home,
        max_events=3,
        cursor=cursor,
    )

    business_facts = [fact for fact in facts if fact["category"] != "collector_health"]
    source_keys = [fact["source_refs"]["source_key"] for fact in business_facts]
    assert source_keys[0].endswith("active.jsonl:00000020")
    assert business_facts[0]["source_specific"]["priority_stream"] == "live_tail"


def test_codex_source_template_understands_real_codex_jsonl_shapes(tmp_path):
    codex_home = tmp_path / ".codex"
    _write_real_shape_session(codex_home)

    facts = collect_facts(
        "collector-codex-real",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    categories = {fact["category"] for fact in facts}
    assert {"tool_call", "tool_execution_failure", "usage", "file_change", "agent_prompt", "agent_reasoning"} <= categories
    prompt_fact = next(fact for fact in facts if fact["category"] == "agent_prompt")
    assert prompt_fact["summary"] == "记录到 用户 Prompt，已上传原始内容。"
    assert prompt_fact["projection"]["content_length"] == len("请检查 Dashboard 为什么看不到原始 Prompt")
    assert prompt_fact["projection"]["prompt_text"] == "请检查 Dashboard 为什么看不到原始 Prompt"
    assert "请检查 Dashboard" in json.dumps(prompt_fact, ensure_ascii=False)
    usage_fact = next(fact for fact in facts if fact["category"] == "usage")
    assert usage_fact["usage"]["units"] == 60
    assert usage_fact["projection"]["context_total_tokens"] == 120
    assert usage_fact["projection"]["cached_input_tokens"] == 60
    assert any(fact.get("error_signature", {}).get("signature_key", "").startswith("tool_execution_failure:") for fact in facts)
    assert any(fact.get("projection", {}).get("command_category") == "test" for fact in facts)
    assert not [fact for fact in facts if fact["category"] == "sensitive_content_exposure"]


def test_codex_source_template_attaches_latest_session_title(tmp_path):
    codex_home = tmp_path / ".codex"
    _write_session(codex_home)
    (codex_home / "session_index.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "session-001", "thread_name": "旧会话名", "updated_at": "2026-06-18T09:00:00Z"}),
                json.dumps({"id": "session-001", "thread_name": "分析信号定义与类型-Grill", "updated_at": "2026-06-18T10:00:00Z"}),
            ]
        ),
        encoding="utf-8",
    )

    facts = collect_facts(
        "collector-codex-title",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    business_facts = [fact for fact in facts if fact["category"] != "collector_health"]
    assert business_facts
    assert {fact["source_refs"]["session_title"] for fact in business_facts} == {"分析信号定义与类型-Grill"}


def test_codex_source_template_attaches_workspace_label_from_global_state(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    workspace_path = "D:/workspace/agentic_factory/apps/agent-observer"
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps(
            {
                "electron-workspace-root-labels": {
                    "D:\\workspace\\agentic_factory\\apps\\agent-observer": "Agent Observer"
                }
            }
        ),
        encoding="utf-8",
    )
    records = [
        {
            "timestamp": "2026-06-18T10:00:00+00:00",
            "type": "session_meta",
            "payload": {"id": "session-workspace", "cwd": workspace_path},
        },
        {
            "timestamp": "2026-06-18T10:01:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "输入"}],
            },
        },
    ]
    (sessions / "session-workspace.jsonl").write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    facts = collect_facts(
        "collector-codex-workspace",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    prompt_fact = next(fact for fact in facts if fact["category"] == "agent_prompt")
    refs = prompt_fact["source_refs"]
    assert refs["workspace_label"] == "Agent Observer"
    assert refs["workspace_path"].endswith("agent-observer")
    assert refs["workspace_alias_source"] == "codex_global_state"
    assert refs["workspace_confidence"] == "high"
