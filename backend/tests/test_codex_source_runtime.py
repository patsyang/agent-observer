from __future__ import annotations

import json
import os

from app.collector_client.telemetry import collect_facts
from source_payloads import write_real_shape_session as _write_real_shape_session


def _timeout_call(call_id: str, run_id: str) -> dict:
    return {
        "timestamp": "2026-06-19T00:50:00.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "shell_command",
            "call_id": call_id,
            "arguments": json.dumps(
                {
                    "command": f"python scripts/ao.py spec-driven resume --run-id {run_id}",
                    "workdir": "D:/workspace/test-project",
                    "timeout_ms": 3600000,
                }
            ),
        },
    }


def _timeout_output(call_id: str) -> dict:
    return {
        "timestamp": "2026-06-19T00:51:14.903Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": "Exit code: 124\nWall time: 3604 seconds\nOutput:\ncommand timed out after 3604035 milliseconds\n",
        },
    }


def test_codex_source_template_pairs_call_output_into_workflow_timeout_fact(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [_timeout_call("call-timeout-001", "run_76317963ed8f"), _timeout_output("call-timeout-001")]
    (sessions / "timeout.jsonl").write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    facts = collect_facts(
        "collector-codex-real",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    timeout_fact = next(fact for fact in facts if fact["category"] == "workflow_step_timeout")
    projection = timeout_fact["projection"]
    assert projection["workflow"] == "spec-driven"
    assert projection["run_id"] == "run_76317963ed8f"
    assert projection["exit_code"] == 124
    assert projection["wall_time_seconds"] == 3604.0
    assert projection["timeout_after_ms"] == 3604035
    assert timeout_fact["projection"]["timeout_type"] == "workflow_step_timeout"
    assert timeout_fact["error_signature"]["signature_key"] == "workflow_step_timeout:spec-driven:run_76317963ed8f:124"


def test_successful_tool_output_with_exit_code_text_is_not_failure_or_timeout(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-19T00:50:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "call-success-with-fixture",
                "arguments": json.dumps({"cmd": "Get-Content backend/tests/test_fixture.py"}),
            },
        },
        {
            "timestamp": "2026-06-19T00:51:14.903Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-success-with-fixture",
                "output": (
                    "Chunk ID: abc\nWall time: 0.3 seconds\nProcess exited with code 0\n"
                    "Output:\nassert 'Exit code: 124' in fixture\ncommand timed out after 3604035 milliseconds\n"
                ),
            },
        },
    ]
    (sessions / "successful-output.jsonl").write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    facts = collect_facts(
        "collector-codex-success-output",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    categories = {fact["category"] for fact in facts}
    assert "tool_execution_timeout" not in categories
    assert "workflow_step_timeout" not in categories
    assert "tool_execution_failure" not in categories


def test_failed_status_with_successful_process_exit_is_not_failure(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-19T00:50:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "call-status-failed-success",
                "arguments": json.dumps({"cmd": "Get-Content fixture.txt"}),
            },
        },
        {
            "timestamp": "2026-06-19T00:51:14.903Z",
            "type": "response_item",
            "status": "failed",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-status-failed-success",
                "output": "Chunk ID: abc\nWall time: 0.3 seconds\nProcess exited with code 0\nOutput:\nall good\n",
            },
        },
    ]
    (sessions / "failed-status-success.jsonl").write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    facts = collect_facts(
        "collector-codex-status-success",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    assert "tool_execution_failure" not in {fact["category"] for fact in facts}


def test_v2_file_cursor_keeps_call_context_across_append_cycles(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "timeout-append.jsonl"
    call_record = _timeout_call("call-timeout-append", "run_append_context")
    output_record = _timeout_output("call-timeout-append")
    path.write_text(json.dumps(call_record) + "\n", encoding="utf-8")
    cursor = {"last_sequence": 0, "sources": {}}

    first = collect_facts("collector-codex-real", 1, "safe_probe", codex_home=codex_home, max_events=1, cursor=cursor)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(output_record) + "\n")
    os.utime(path, None)
    second = collect_facts("collector-codex-real", 2, "safe_probe", codex_home=codex_home, max_events=10, cursor=cursor)

    assert cursor["call_context"]["call-timeout-append"]["record"]["payload"]["type"] == "function_call"
    assert {fact["source_event_id"] for fact in first if fact["category"] != "collector_health"}.isdisjoint(
        {fact["source_event_id"] for fact in second if fact["category"] != "collector_health"}
    )
    timeout_fact = next(fact for fact in second if fact["category"] == "workflow_step_timeout")
    assert timeout_fact["projection"]["run_id"] == "run_append_context"


def test_v2_file_cursor_persists_when_initial_cursor_is_empty(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "empty-cursor-start.jsonl"
    records = [
        {
            "timestamp": f"2026-06-19T00:0{index}:00.000Z",
            "type": "usage",
            "total_tokens": 100 + index,
            "conversation_id": f"conversation-{index}",
            "session_id": "empty-cursor-start",
        }
        for index in range(4)
    ]
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    cursor = {}

    first = collect_facts(
        "collector-codex-empty-cursor",
        1,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor=cursor,
    )
    second = collect_facts(
        "collector-codex-empty-cursor",
        2,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor=cursor,
    )

    first_ids = {fact["source_event_id"] for fact in first}
    second_ids = {fact["source_event_id"] for fact in second}
    assert cursor["sources"]
    assert len(first_ids) == 2
    assert len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)


def test_v2_file_cursor_reads_only_current_cycle_batch(tmp_path, monkeypatch):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "large-backfill.jsonl"
    records = [
        {
            "timestamp": f"2026-06-19T00:{index % 60:02d}:00.000Z",
            "type": "usage",
            "total_tokens": 100 + index,
            "conversation_id": f"conversation-{index}",
            "session_id": "large-backfill",
        }
        for index in range(500)
    ]
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    parse_count = 0
    real_loads = json.loads

    def bounded_loads(value: str):
        nonlocal parse_count
        parse_count += 1
        if parse_count > 3:
            raise AssertionError("collector read beyond current max_events batch")
        return real_loads(value)

    monkeypatch.setattr("app.collector_client.source_reader.json.loads", bounded_loads)

    facts = collect_facts(
        "collector-codex-large",
        1,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor={"last_sequence": 0, "sources": {}},
    )

    assert len([fact for fact in facts if fact["category"] != "collector_health"]) == 2


def test_workspace_hint_does_not_scan_deep_session_files(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "deep-session-meta.jsonl"
    records = [
        {
            "timestamp": f"2026-06-19T00:{index % 60:02d}:00.000Z",
            "type": "usage",
            "total_tokens": 100 + index,
            "conversation_id": f"conversation-{index}",
            "session_id": "deep-session-meta",
        }
        for index in range(40)
    ]
    records.append(
        {
            "timestamp": "2026-06-19T00:50:00.000Z",
            "type": "session_meta",
            "payload": {"cwd": "D:/workspace/too-deep"},
        }
    )
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    facts = collect_facts(
        "collector-codex-deep",
        1,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor={"last_sequence": 0, "sources": {}},
    )

    business_facts = [fact for fact in facts if fact["category"] != "collector_health"]
    assert len(business_facts) == 2
    assert all("workspace_id" not in fact["source_refs"] for fact in business_facts)


def test_v2_file_cursor_continues_same_file_after_cycle_limit(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "large-backfill.jsonl"
    records = [
        {
            "timestamp": f"2026-06-19T00:0{index}:00.000Z",
            "type": "usage",
            "total_tokens": 100 + index,
            "conversation_id": f"conversation-{index}",
            "session_id": "large-backfill",
        }
        for index in range(4)
    ]
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    cursor = {"last_sequence": 0, "sources": {}}

    first = collect_facts(
        "collector-codex-large",
        1,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor=cursor,
    )
    second = collect_facts(
        "collector-codex-large",
        2,
        "safe_probe",
        codex_home=codex_home,
        max_events=2,
        cursor=cursor,
    )

    first_ids = [fact["source_event_id"] for fact in first if fact["category"] != "collector_health"]
    second_ids = [fact["source_event_id"] for fact in second if fact["category"] != "collector_health"]
    assert len(first_ids) == 2
    assert len(second_ids) == 2
    assert set(first_ids).isdisjoint(second_ids)


def test_v2_file_cursor_prioritizes_live_tail_while_backfill_is_unfinished(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / "active-long-session.jsonl"
    old_records = [
        {
            "timestamp": f"2026-06-19T00:{index:02d}:00.000Z",
            "type": "usage",
            "total_tokens": 100 + index,
            "conversation_id": f"old-conversation-{index}",
            "session_id": "active-long-session",
        }
        for index in range(10)
    ]
    path.write_text("\n".join(json.dumps(record) for record in old_records) + "\n", encoding="utf-8")
    cursor = {"last_sequence": 0, "sources": {}}

    collect_facts("collector-codex-live", 1, "safe_probe", codex_home=codex_home, max_events=2, cursor=cursor)
    live_record = {
        "timestamp": "2026-06-21T01:30:00.000Z",
        "type": "usage",
        "total_tokens": 999,
        "conversation_id": "live-conversation",
        "session_id": "active-long-session",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(live_record) + "\n")
    os.utime(path, None)

    facts = collect_facts("collector-codex-live", 2, "safe_probe", codex_home=codex_home, max_events=1, cursor=cursor)

    live_fact = next(fact for fact in facts if fact["category"] != "collector_health")
    assert live_fact["occurred_at"] == "2026-06-21T01:30:00.000Z"
    assert live_fact["projection"]["units"] == 999
    assert live_fact["source_specific"]["priority_stream"] == "live_tail"


def test_codex_source_template_uploads_raw_prompt_by_default(tmp_path):
    codex_home = tmp_path / ".codex"
    _write_real_shape_session(codex_home)

    facts = collect_facts(
        "collector-codex-real",
        1,
        "raw_enabled",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    prompt_fact = next(fact for fact in facts if fact["category"] == "agent_prompt")
    assert prompt_fact["summary"] == "记录到 用户 Prompt，已上传原始内容。"
    assert "check dashboard prompt visibility" in prompt_fact["raw_content"]
    assert prompt_fact["projection"]["prompt_text"] == "check dashboard prompt visibility"
    reasoning_fact = next(fact for fact in facts if fact["category"] == "agent_reasoning")
    assert reasoning_fact["projection"]["content_length"] == len("reasoning about evidence chain refresh")


def test_tool_execution_failure_signature_groups_same_failure_shape(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-18T11:01:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "output": "Exit code: 1\nOutput from first failed command",
            },
        },
        {
            "timestamp": "2026-06-18T11:02:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "output": "Exit code: 1\nDifferent stderr text from the same failure shape",
            },
        },
    ]
    (sessions / "same-error-shape.jsonl").write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    facts = collect_facts(
        "collector-codex-errors",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    signatures = {
        fact["error_signature"]["signature_key"]
        for fact in facts
        if fact["category"] == "tool_execution_failure"
    }

    assert signatures == {"tool_execution_failure:function_call_output:function_call_output:1"}


def test_conversation_ref_stable_across_turns_with_same_session_id(tmp_path):
    """同 session_id 不同 turn_id 的事件应生成相同 conversation_ref。

    回归：曾因 payload.turn_id 优先于 session_id 导致会话碎片化（39 个 conversation_ref），
    与 materialize.py 的"会话级 ref"设计意图冲突。
    """
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-07-14T10:00:00+00:00",
            "type": "usage",
            "total_tokens": 100,
            "session_id": "session-stable-conv-ref",
            "payload": {"turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-07-14T10:01:00+00:00",
            "type": "usage",
            "total_tokens": 200,
            "session_id": "session-stable-conv-ref",
            "payload": {"turn_id": "turn-2"},
        },
        {
            "timestamp": "2026-07-14T10:02:00+00:00",
            "type": "usage",
            "total_tokens": 300,
            "session_id": "session-stable-conv-ref",
            # 无 turn_id 的事件（content/usage 类常见）也应归到同一 conversation_ref
        },
    ]
    (sessions / "stable-conv-ref.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )

    facts = collect_facts(
        "collector-codex-stable-conv",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    usage_facts = [fact for fact in facts if fact["category"] == "usage"]
    assert len(usage_facts) >= 2
    conv_refs = {fact["source_refs"]["conversation_ref"] for fact in usage_facts}
    assert len(conv_refs) == 1, f"同 session_id 的事件应归到同一 conversation_ref，实际: {conv_refs}"


def test_conversation_ref_falls_back_to_turn_id_when_session_id_missing(tmp_path):
    """session_id 缺失时，turn_id 仍可作为 conversation_ref 兜底。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-07-14T10:00:00+00:00",
            "type": "usage",
            "total_tokens": 100,
            "payload": {"turn_id": "turn-fallback-only"},
        },
    ]
    (sessions / "turn-fallback.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )

    facts = collect_facts(
        "collector-codex-turn-fallback",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    usage_facts = [fact for fact in facts if fact["category"] == "usage"]
    assert usage_facts
    conv_ref = usage_facts[0]["source_refs"]["conversation_ref"]
    assert conv_ref, "turn_id 兜底应生成非空 conversation_ref"


def _custom_tool_call(call_id: str, js_input: str, status: str = "completed") -> dict:
    """构造 Codex 新格式 custom_tool_call 事件。"""
    return {
        "timestamp": "2026-07-14T10:00:00.000Z",
        "type": "response_item",
        "session_id": "session-custom-tool",
        "payload": {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": call_id,
            "id": call_id,
            "status": status,
            "input": js_input,
        },
    }


def _custom_tool_call_output(call_id: str, output: object) -> dict:
    """构造 Codex 新格式 custom_tool_call_output 事件。"""
    return {
        "timestamp": "2026-07-14T10:01:00.000Z",
        "type": "response_item",
        "session_id": "session-custom-tool",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": output,
        },
    }


def test_custom_tool_call_output_list_with_exit_code_produces_failure(tmp_path):
    """custom_tool_call_output 的 output 是 list 且含退出码文本时，应生成 tool_execution_failure。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        _custom_tool_call(
            "call-list-exit",
            'tools.exec_command({cmd:"pnpm test"})',
        ),
        _custom_tool_call_output(
            "call-list-exit",
            [
                {"text": "Script completed\nWall time: 0.8 seconds\nProcess exited with code 1\nOutput:\n", "type": "input_text"},
                {"text": "test failed", "type": "input_text"},
            ],
        ),
    ]
    (sessions / "custom-list-exit.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )

    facts = collect_facts(
        "collector-codex-list-exit",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    failure_facts = [fact for fact in facts if fact["category"] == "tool_execution_failure"]
    assert failure_facts, "list output 含退出码 1 时应生成 tool_execution_failure"
    assert failure_facts[0]["projection"]["exit_code"] == 1


def test_custom_tool_call_output_uses_call_status_when_exit_code_missing(tmp_path):
    """custom_tool_call_output 无退出码但关联的 custom_tool_call status=failed 时，应判定为 error。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        _custom_tool_call(
            "call-status-failed",
            'tools.exec_command({cmd:"playwright test"})',
            status="failed",
        ),
        _custom_tool_call_output(
            "call-status-failed",
            [
                {"text": "Script completed\nWall time: 5.5 seconds\nOutput:\n1 failed\n3 passed\n", "type": "input_text"},
            ],
        ),
    ]
    (sessions / "custom-status-failed.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )

    facts = collect_facts(
        "collector-codex-status-failed",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    failure_facts = [fact for fact in facts if fact["category"] == "tool_execution_failure"]
    assert failure_facts, "call status=failed 且无退出码时应生成 tool_execution_failure"


def test_custom_tool_call_output_completed_not_error(tmp_path):
    """custom_tool_call status=completed 且 output 无退出码时，不应判定为 error。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        _custom_tool_call(
            "call-completed-ok",
            'tools.exec_command({cmd:"pnpm typecheck"})',
            status="completed",
        ),
        _custom_tool_call_output(
            "call-completed-ok",
            [
                {"text": "Script completed\nWall time: 2.0 seconds\nOutput:\ntypecheck passed\n", "type": "input_text"},
            ],
        ),
    ]
    (sessions / "custom-completed-ok.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )

    facts = collect_facts(
        "collector-codex-completed-ok",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_sequence": 0, "sources": {}},
    )

    categories = {fact["category"] for fact in facts}
    assert "tool_execution_failure" not in categories, "status=completed 且无退出码时不应生成 error"
