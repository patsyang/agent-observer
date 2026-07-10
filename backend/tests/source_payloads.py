from __future__ import annotations

import json

from app.collector_client.version import COLLECTOR_CLIENT_VERSION, COLLECTOR_PROTOCOL_VERSION


def default_versions() -> dict:
    """返回当前 collector 客户端的协议与实现版本，供测试构造 payload 时引用常量而非硬编码字符串。"""
    return {
        "protocol_version": COLLECTOR_PROTOCOL_VERSION,
        "agent_version": COLLECTOR_CLIENT_VERSION,
    }


def default_sources() -> list[dict]:
    return [
        {
            "source_id": "codex-local",
            "agent_type": "codex",
            "source_kind": "codex_local",
            "display_name": "Codex Local",
            "source_status": "online",
            "reason_code": "online",
            "capabilities": {"raw_upload_default": True},
        },
        {
            "source_id": "workbuddy-local",
            "agent_type": "workbuddy",
            "source_kind": "workbuddy_local",
            "display_name": "WorkBuddy Local",
            "source_status": "online",
            "reason_code": "online",
            "capabilities": {"raw_upload_default": True},
        },
    ]


def write_codex_fixture(codex_home):
    """写入用于打包 collector 测试的 Codex session fixture。"""
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-18T10:00:00+00:00",
            "type": "tool_result",
            "tool": "shell",
            "exit_code": 1,
            "phase": "test",
            "conversation_id": "conversation-package",
            "session_id": "session-package",
            "summary": "test command failed",
        },
        {
            "timestamp": "2026-06-18T10:02:00+00:00",
            "type": "usage",
            "total_tokens": 120,
            "activity_tags": ["test_run"],
            "conversation_id": "conversation-package",
            "session_id": "session-package",
        },
        {
            "timestamp": "2026-06-18T10:03:00+00:00",
            "type": "message",
            "role": "user",
            "content": "check dashboard prompt visibility",
            "conversation_id": "conversation-package",
            "session_id": "session-package",
        },
    ]
    (sessions / "session-package.jsonl").write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")


def write_workbuddy_fixture(workbuddy_home):
    """写入用于打包 collector 测试的 WorkBuddy session fixture。"""
    projects = workbuddy_home / "projects" / "demo"
    projects.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-18T10:04:00+00:00",
            "type": "message",
            "role": "user",
            "content": "check workbuddy collection",
            "sessionId": "session-workbuddy-package",
        },
        {
            "timestamp": "2026-06-18T10:05:00+00:00",
            "type": "function_call_result",
            "name": "shell",
            "output": "1 passed",
            "sessionId": "session-workbuddy-package",
        },
    ]
    (projects / "conversation.jsonl").write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")


def write_real_shape_session(codex_home, name: str = "real-shape.jsonl") -> None:
    """写入模拟真实 Codex JSONL 形状的 session fixture。"""
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
                    "workdir": "D:/workspace/test-project",
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
                    "command": 'git commit -m "test commit"',
                    "workdir": "D:/workspace/test-project",
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
                    "workdir": "D:/workspace/test-project",
                }),
            },
        },
        {
            "timestamp": "2026-06-18T11:04:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "check dashboard prompt visibility"}],
            },
        },
        {
            "timestamp": "2026-06-18T11:05:00+00:00",
            "type": "event_msg",
            "payload": {
                "type": "reasoning",
                "summary": "reasoning about evidence chain refresh",
            },
        },
    ]
    (sessions / name).write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
