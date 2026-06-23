from __future__ import annotations

import json

from app.collector_client.config import SourceConfig
from app.collector_client.sources.workbuddy import collect_workbuddy_source


def test_workbuddy_source_collects_supported_local_logs(tmp_path):
    root = tmp_path / ".workbuddy"
    _write_json(root / "sessions" / "123.json", {"sessionId": "session-a", "mode": "interactive", "updatedAt": "2026-06-23T01:00:00+00:00"})
    _write_jsonl(
        root / "projects" / "demo" / "conversation.jsonl",
        [
            {"type": "message", "role": "user", "content": "检查 WorkBuddy 采集", "sessionId": "session-a", "timestamp": 1781345565734},
            {"type": "reasoning", "role": "assistant", "content": "分析采集范围", "sessionId": "session-a", "timestamp": 1781345565735},
            {
                "type": "message",
                "role": "assistant",
                "content": "WorkBuddy 响应",
                "sessionId": "session-a",
                "timestamp": 1781345565735,
                "providerData": {
                    "model": "deepseek-v4-pro",
                    "provider": "tencent",
                    "traceId": "trace-project-usage",
                    "usage": {
                        "inputTokens": 1000,
                        "outputTokens": 120,
                        "totalTokens": 1120,
                        "inputTokensDetails": [{"cached_tokens": 800}],
                        "outputTokensDetails": [{"reasoning_tokens": 40}],
                    },
                    "rawUsage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 120,
                        "total_tokens": 1120,
                        "prompt_cache_hit_tokens": 800,
                        "prompt_cache_write_tokens": 30,
                        "credit": 2.5,
                        "completion_tokens_details": {"reasoning_tokens": 40},
                    },
                },
                "message": {"usage": {"input_tokens": 1000, "output_tokens": 120, "total_tokens": 1120, "cache_read_input_tokens": 800}},
            },
            {"type": "function_call", "name": "shell", "arguments": {"command": "python -m pytest"}, "sessionId": "session-a", "timestamp": 1781345565736},
            {"type": "function_call_result", "name": "shell", "output": "1 passed", "sessionId": "session-a", "timestamp": 1781345565737},
        ],
    )
    _write_json(
        root / "traces" / "123" / "trace_demo.json",
        {"trace": {"traceId": "trace-project-usage", "totalTokens": 1120, "modelInfo": {"totalInputTokens": 1000, "totalOutputTokens": 120, "totalCachedTokens": 800}}, "sessionId": "session-a"},
    )
    _write_json(root / "traces" / "123" / "trace_fallback.json", {"trace": {"traceId": "trace-fallback", "totalTokens": 321}, "sessionId": "session-a"})
    _write_jsonl(
        root / "audit-log" / "2026-06-23.jsonl",
        [{"eventType": "tool_approval", "decision": "approved", "commandPreview": "python -m pytest", "sessionId": "session-a", "timestamp": 1781345565735}],
    )
    _write_json(root / "tasks" / "session-a" / "1.json", {"id": "task-1", "status": "completed", "subject": "完成接入"})

    result = collect_workbuddy_source(
        SourceConfig("workbuddy-local", "workbuddy", "workbuddy_local", "WorkBuddy Local", root, True),
        collector_id="collector-a",
        sequence=1,
        telemetry_mode="safe_probe",
        history_window_days=7,
        max_events=20,
        cursor={},
    )

    categories = {fact["category"] for fact in result.facts}
    assert result.status == "online"
    assert {"agent_prompt", "agent_reasoning", "usage", "tool_call", "tool_result", "task_status"} <= categories
    assert "collector_health" not in categories
    assert "collector_source_status" not in categories
    assert all(fact["source_refs"]["source_id"] == "workbuddy-local" for fact in result.facts)
    prompt = next(fact for fact in result.facts if fact["category"] == "agent_prompt")
    assert prompt["upload_raw"] is True
    assert prompt["raw_content"]
    response = next(fact for fact in result.facts if fact["category"] == "agent_response")
    assert response["usage"]["units"] == 320
    assert response["usage"]["input_tokens"] == 1000
    assert response["usage"]["cached_input_tokens"] == 800
    assert response["usage"]["output_tokens"] == 120
    assert response["usage"]["cache_write_input_tokens"] == 30
    assert response["usage"]["reasoning_output_tokens"] == 40
    assert response["usage"]["model"] == "deepseek-v4-pro"
    assert response["usage"]["provider"] == "tencent"
    assert response["usage"]["credit"] == 2.5
    assert response["usage"]["unit_basis"] == "non_cached_input_plus_output"
    assert any(fact["fact_type"] == "unknown" for fact in result.facts if fact["source_specific"]["event_type"] == "trace")


def test_workbuddy_trace_model_info_is_fallback_usage(tmp_path):
    root = tmp_path / ".workbuddy"
    _write_json(
        root / "traces" / "123" / "trace_fallback.json",
        {
            "trace": {
                "traceId": "trace-fallback",
                "totalTokens": 1120,
                "modelInfo": {
                    "models": ["glm-5.1"],
                    "totalInputTokens": 1000,
                    "totalOutputTokens": 120,
                    "totalCachedTokens": 800,
                    "callCount": 1,
                },
            },
            "sessionId": "session-a",
        },
    )

    result = collect_workbuddy_source(
        SourceConfig("workbuddy-local", "workbuddy", "workbuddy_local", "WorkBuddy Local", root, True),
        collector_id="collector-a",
        sequence=1,
        telemetry_mode="safe_probe",
        history_window_days=7,
        max_events=20,
        cursor={},
    )

    usage = next(fact for fact in result.facts if fact["category"] == "usage")
    assert usage["usage"]["units"] == 320
    assert usage["usage"]["input_tokens"] == 1000
    assert usage["usage"]["cached_input_tokens"] == 800
    assert usage["usage"]["output_tokens"] == 120
    assert usage["usage"]["model"] == "glm-5.1"


def test_workbuddy_project_usage_suppresses_trace_fallback_by_request_id(tmp_path):
    root = tmp_path / ".workbuddy"
    _write_jsonl(
        root / "projects" / "demo" / "conversation.jsonl",
        [
            {
                "type": "message",
                "role": "assistant",
                "content": "WorkBuddy 响应",
                "sessionId": "session-a",
                "timestamp": 1781345565735,
                "providerData": {
                    "conversationRequestId": "request-usage-a",
                    "usage": {"inputTokens": 500, "outputTokens": 50, "totalTokens": 550},
                },
            }
        ],
    )
    _write_json(
        root / "traces" / "123" / "trace_demo.json",
        {"trace": {"conversationRequestId": "request-usage-a", "totalTokens": 550}, "sessionId": "session-a"},
    )

    result = collect_workbuddy_source(
        SourceConfig("workbuddy-local", "workbuddy", "workbuddy_local", "WorkBuddy Local", root, True),
        collector_id="collector-a",
        sequence=1,
        telemetry_mode="safe_probe",
        history_window_days=7,
        max_events=20,
        cursor={},
    )

    usage_bearing_facts = [fact for fact in result.facts if fact.get("usage")]
    assert len(usage_bearing_facts) == 1
    assert usage_bearing_facts[0]["usage"]["units"] == 550
    assert not any(fact["category"] == "usage" for fact in result.facts)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
