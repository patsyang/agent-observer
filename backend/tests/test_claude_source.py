from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.collector_client.config import SourceConfig
from app.collector_client.sources.claude import collect_claude_source


def _make_config(root):
    return SourceConfig("claude-local", "claude", "claude_local", "Claude Code Local", root, True)


def _collect(root, cursor=None, **kwargs):
    return collect_claude_source(
        _make_config(root),
        collector_id="collector-a",
        sequence=1,
        telemetry_mode="safe_probe",
        history_window_days=kwargs.get("history_window_days", 7),
        max_events=kwargs.get("max_events", 50),
        cursor=cursor if cursor is not None else {},
    )


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _session_file(root, name="D--test-project", session="test-session.jsonl"):
    return root / "projects" / name / session


def test_user_message_collects_content_prompt(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": "hello claude"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    assert result.status == "online"
    fact = result.facts[0]
    assert fact["fact_type"] == "content"
    assert fact["category"] == "agent_prompt"
    assert fact["projection"]["content_text"] == "hello claude"


def test_assistant_text_collects_content_response(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "hi there"}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "agent_response")
    assert fact["fact_type"] == "content"
    assert fact["projection"]["content_text"] == "hi there"


def test_assistant_tool_use_collects_tool_call(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "ls"}}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "tool_call")
    assert fact["fact_type"] == "tool"
    assert fact["projection"]["tool_name"] == "Bash"
    assert fact["projection"]["tool_call_id"] == "tool-1"
    assert fact["projection"]["command"] == "ls"
    assert fact["projection"]["command_excerpt"] == "ls"
    assert fact["projection"]["command_category"] == "shell"


def test_assistant_tool_use_without_command_falls_back_to_json(tmp_path):
    """无 command 字段的工具（如 Read）兜底为 JSON 串。"""
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "tool_use", "id": "tool-2", "name": "Read", "input": {"file_path": "README.md"}}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "tool_call")
    assert fact["projection"]["command_excerpt"] == '{"file_path": "README.md"}'
    assert "command" not in fact["projection"] or not fact["projection"]["command"]
    assert fact["projection"]["command_category"] == ""


def test_assistant_tool_use_with_cmd_key_extracts_command(tmp_path):
    """工具输入用 cmd 键（非 command）时也能提取命令。"""
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "tool_use", "id": "tool-3", "name": "Bash", "input": {"cmd": "git status"}}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "tool_call")
    assert fact["projection"]["command"] == "git status"
    assert fact["projection"]["command_category"] == "git"


def test_assistant_tool_use_long_command_truncated_with_ellipsis(tmp_path):
    """超长命令截断后带 ... 后缀。"""
    root = tmp_path / ".claude"
    long_command = "python -m pytest " + " ".join(["test_case_%d" % i for i in range(50)])
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "tool_use", "id": "tool-4", "name": "Bash", "input": {"command": long_command}}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "tool_call")
    excerpt = fact["projection"]["command_excerpt"]
    assert excerpt.endswith("...")
    assert len(excerpt) == 182  # text[:179] + "..."


def test_user_tool_result_collects_tool_result(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "1 passed"}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "tool_result")
    assert fact["fact_type"] == "tool"
    assert "1 passed" in fact["projection"]["result_excerpt"]


def test_assistant_usage_collects_usage_fact(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 10}}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "usage")
    assert fact["fact_type"] == "usage"
    assert fact["usage"]["input_tokens"] == 100
    assert fact["usage"]["output_tokens"] == 20
    assert fact["usage"]["cached_input_tokens"] == 50
    assert fact["usage"]["cache_write_input_tokens"] == 10
    assert fact["usage"]["activity_tag"] == "claude_turn"
    assert fact["usage"]["model"] == "claude-sonnet-4"


def test_tool_result_error_collects_error_fact(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "Exit code: 1\nTraceback (most recent call last):\n  File \"x\""}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "tool_execution_failure")
    assert fact["fact_type"] == "error"
    assert fact["error_signature"]["exit_code"] == 1
    assert fact["severity"] == "high"


def test_cursor_skips_unchanged_file(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    cursor = {}
    first = _collect(root, cursor=cursor)
    assert len(first.facts) == 1
    second = _collect(root, cursor=cursor)
    assert second.facts == []


def test_cursor_continues_on_append(tmp_path):
    root = tmp_path / ".claude"
    path = _session_file(root)
    _write_jsonl(path, [
        {"type": "user", "message": {"role": "user", "content": "first"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    cursor = {}
    first = _collect(root, cursor=cursor)
    assert len(first.facts) == 1
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": "second"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:01:00+00:00"}, ensure_ascii=False) + "\n")
    second = _collect(root, cursor=cursor)
    assert len(second.facts) == 1
    assert second.facts[0]["projection"]["content_text"] == "second"


def test_cursor_resets_on_truncate(tmp_path):
    root = tmp_path / ".claude"
    path = _session_file(root)
    _write_jsonl(path, [
        {"type": "user", "message": {"role": "user", "content": "first"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
        {"type": "user", "message": {"role": "user", "content": "second"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:01:00+00:00"},
    ])
    cursor = {}
    first = _collect(root, cursor=cursor)
    assert len(first.facts) == 2
    _write_jsonl(path, [
        {"type": "user", "message": {"role": "user", "content": "reset"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:02:00+00:00"},
    ])
    second = _collect(root, cursor=cursor)
    assert len(second.facts) == 1
    assert second.facts[0]["projection"]["content_text"] == "reset"


def test_cursor_advances_when_limit_reached_mid_record(tmp_path):
    """Regression: cursor must advance past a record even when max_events limit is hit, avoiding livelock."""
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": "first"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
        {"type": "user", "message": {"role": "user", "content": "second"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:01:00+00:00"},
    ])
    cursor = {}
    first = _collect(root, cursor=cursor, max_events=1)
    assert len(first.facts) == 1
    assert first.facts[0]["projection"]["content_text"] == "first"
    second = _collect(root, cursor=cursor, max_events=1)
    assert len(second.facts) == 1
    assert second.facts[0]["projection"]["content_text"] == "second"


def test_skips_attachment_and_queue_operation(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "queue-operation", "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
        {"type": "attachment", "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    assert result.facts == []


def test_ai_title_extracted_to_session_title(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "ai-title", "aiTitle": "My Cool Session", "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:01:00+00:00"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "agent_prompt")
    assert fact["source_refs"]["session_title"] == "My Cool Session"


def test_source_refs_has_claude_agent_type(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    assert result.facts[0]["source_refs"]["agent_type"] == "claude"


def test_source_template_is_claude_local(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    assert result.facts[0]["source_specific"]["source_template"] == "claude.local.sessions.v1"


def test_history_window_filters_old_records(tmp_path):
    root = tmp_path / ".claude"
    path = _session_file(root)
    _write_jsonl(path, [
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    old_time = time.time() - 30 * 86400
    os.utime(path, (old_time, old_time))
    result = _collect(root, history_window_days=7)
    assert result.facts == []


def test_tool_use_tool_result_association(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "ls"}}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "file1\nfile2"}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:01:00+00:00"},
    ])
    result = _collect(root)
    tool_call = next(f for f in result.facts if f["category"] == "tool_call")
    tool_result = next(f for f in result.facts if f["category"] == "tool_result")
    assert tool_call["projection"]["tool_call_id"] == "tool-1"
    assert tool_result["projection"]["tool_call_id"] == "tool-1"
    assert tool_result["projection"]["tool_name"] == "Bash"


def test_assistant_text_tool_use_and_usage_have_distinct_source_event_ids(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "ls"}},
        ], "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 10}}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    result = _collect(root)
    assert len(result.facts) == 3
    ids = {fact["source_event_id"] for fact in result.facts}
    assert len(ids) == 3
    categories = {fact["category"] for fact in result.facts}
    assert categories == {"agent_response", "tool_call", "usage"}


def test_decode_project_dir_fallback(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(root / "projects" / "D--test-project" / "s1.jsonl", [
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    fact = result.facts[0]
    assert fact["source_refs"]["workspace_path"] == "D:\\test\\project"


def test_collect_sources_dispatches_claude(tmp_path):
    from app.collector_client.config import CollectorConfig
    from app.collector_client.sources import collect_sources

    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    config = CollectorConfig(
        server_url="http://localhost",
        collector_id="collector-a",
        state_path=tmp_path / "state.json",
        telemetry_mode="safe_probe",
        collection_interval_seconds=5,
        heartbeat_interval_seconds=10,
        sources=[SourceConfig("claude-local", "claude", "claude_local", "Claude Code Local", root, True)],
        history_window_days=7,
        max_events_per_cycle=50,
        upload_batch_size=100,
        evidence_mode="structured_projection",
    )
    results = collect_sources(config, {}, 1)
    claude_results = [r for r in results if r.config.source_kind == "claude_local"]
    assert len(claude_results) == 1
    assert claude_results[0].status == "online"
    assert claude_results[0].facts


def test_default_root_for_claude_local():
    from app.collector_client.config import _source_config

    source = _source_config({"source_id": "claude-local", "agent_type": "claude", "source_kind": "claude_local"}, Path("."))
    assert source.root == Path.home() / ".claude"


def test_ai_title_after_user_message_backfills_session_title(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": "hello"}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
        {"type": "ai-title", "aiTitle": "Late Title", "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:01:00+00:00"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "agent_prompt")
    assert fact["source_refs"]["session_title"] == "Late Title"


def test_seen_message_ids_persist_across_cycles(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 100, "output_tokens": 20}}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00", "model": "claude-sonnet-4"},
    ])
    cursor = {}
    first = _collect(root, cursor=cursor)
    assert any(f["category"] == "usage" for f in first.facts)
    assert cursor["claude_seen_message_ids"] == ["m1"]


def test_tool_result_error_signature_has_signature_key_and_category(tmp_path):
    root = tmp_path / ".claude"
    _write_jsonl(_session_file(root), [
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "content": "Exit code: 1\nTraceback (most recent call last):\n  File \"x\""}]}, "sessionId": "s1", "cwd": "D:\\test", "timestamp": "2026-06-30T01:00:00+00:00"},
    ])
    result = _collect(root)
    fact = next(f for f in result.facts if f["category"] == "tool_execution_failure")
    assert fact["error_signature"]["signature_key"] == "tool_execution_failure:unknown:tool_result:1"
    assert fact["error_signature"]["category"] == "tool_execution_failure"
