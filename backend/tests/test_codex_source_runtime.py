from __future__ import annotations

import json
import os

from app.collector_client.telemetry import collect_facts
from backend.tests.test_codex_source_template import _write_real_shape_session


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
                    "workdir": "D:/workspace/agentic_factory",
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


def test_codex_source_template_pairs_call_output_into_command_timeout_fact(tmp_path):
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
        cursor={"last_source_key": ""},
    )

    timeout_fact = next(fact for fact in facts if fact["category"] == "command_timeout")
    projection = timeout_fact["projection"]
    assert projection["workflow"] == "spec-driven"
    assert projection["run_id"] == "run_76317963ed8f"
    assert projection["exit_code"] == 124
    assert projection["wall_time_seconds"] == 3604.0
    assert projection["timeout_after_ms"] == 3604035
    assert timeout_fact["error_signature"]["signature_key"] == "command_timeout:spec-driven:run_76317963ed8f:124"


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
    timeout_fact = next(fact for fact in second if fact["category"] == "command_timeout")
    assert timeout_fact["projection"]["run_id"] == "run_append_context"


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
    assert parse_count == 2


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


def test_codex_source_template_uploads_raw_prompt_when_enabled(tmp_path):
    codex_home = tmp_path / ".codex"
    _write_real_shape_session(codex_home)

    facts = collect_facts(
        "collector-codex-real",
        1,
        "raw_enabled",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_source_key": ""},
        upload_raw=True,
    )

    prompt_fact = next(fact for fact in facts if fact["category"] == "codex_prompt")
    assert prompt_fact["summary"] == "记录到 Codex 用户 Prompt，已上传原始内容。"
    assert "请检查 Dashboard 为什么看不到原始 Prompt" in prompt_fact["raw_content"]
    assert prompt_fact["projection"]["prompt_text"] == "请检查 Dashboard 为什么看不到原始 Prompt"
    reasoning_fact = next(fact for fact in facts if fact["category"] == "codex_reasoning")
    assert reasoning_fact["projection"]["content_length"] == len("模型正在判断证据链刷新路径")


def test_codex_error_signature_groups_same_failure_shape(tmp_path):
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
        cursor={"last_source_key": ""},
    )

    signatures = {
        fact["error_signature"]["signature_key"]
        for fact in facts
        if fact["category"] == "codex_error"
    }

    assert signatures == {"codex_error:function_call_output:response_item:1:function_call_output"}
