"""敏感数据回归测试：验证 MCP 事件 arguments 中的敏感数据能被 detect_for_fact 命中。

依赖 Task 1 的 arguments() 回退：MCP 事件 payload.invocation.arguments 被提取后，
敏感值进入 raw_content / projection，detect_for_fact 能扫到。
"""
from __future__ import annotations

import json

from app.collector_client.fact_mapper import _tool_fact
from app.sensitive.engine import detect_for_fact


def _common() -> dict:
    return {
        "source_event_id": "evt-mcp-sensitive-1",
        "occurred_at": "2026-07-12T10:00:00+00:00",
        "span": "codex-session:mcp-sensitive",
        "raw_hash": "rawhashsensitive01",
        "source_refs": {"conversation_ref": "ref:conv1", "session_ref": "ref:sess1"},
        "source_specific": {"event_type": "event_msg:mcp_tool_call_end"},
        "upload_raw": True,
        "raw_content": "{}",
    }


def _mcp_record_with_sensitive_key() -> dict:
    """MCP 事件，invocation.arguments 中包含 Anthropic API key 形态的敏感值。"""
    api_key = "sk-ant-api03-test1234567890test1234567890test1234567890"
    return {
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "call_id": "call_sensitive_1",
            "duration": {"nanos": 1500000, "secs": 0},
            "invocation": {
                "server": "node_repl",
                "tool": "js",
                "arguments": {"code": f"process.env.ANTHROPIC_API_KEY = '{api_key}'", "timeout_ms": 30000},
            },
            "result": {"Ok": {"content": [{"text": "ok", "type": "text"}], "isError": False}},
        },
    }


def test_mcp_event_sensitive_api_key_detected_in_projection_and_raw():
    """MCP 事件 arguments 中的 sk-ant-api03-... 被 detect_for_fact 命中 token 类别。"""
    record = _mcp_record_with_sensitive_key()
    fact = _tool_fact(_common(), record)
    assert fact is not None

    projection_json = json.dumps(fact["projection"], ensure_ascii=False, sort_keys=True, default=str)
    raw_content = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)

    matches = detect_for_fact(projection_json, raw_content)
    categories = {m["category"] for m in matches}
    assert "token" in categories, f"期望命中 token 类别，实际命中: {categories}"

    anthropic_hits = [m for m in matches if "sk-ant-" in m.get("matched_value", "")]
    assert anthropic_hits, "期望命中 sk-ant-api03-... 形态的 Anthropic API key"
    assert all(m["confidence"] == "high" for m in anthropic_hits), anthropic_hits


def test_mcp_event_sensitive_detected_from_raw_content_only():
    """即使 projection 不含敏感值（仅 argument_keys），raw_content 仍能被扫到。"""
    record = _mcp_record_with_sensitive_key()
    fact = _tool_fact(_common(), record)
    assert fact is not None

    # projection 中 argument_keys 只含字段名（code/timeout_ms），不含值
    projection_json = json.dumps(fact["projection"], ensure_ascii=False, sort_keys=True, default=str)
    raw_content = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)

    # 仅传 raw_content
    matches_raw_only = detect_for_fact("", raw_content)
    cats_raw = {m["category"] for m in matches_raw_only}
    assert "token" in cats_raw, f"仅 raw_content 也应命中 token，实际: {cats_raw}"


def test_mcp_event_without_sensitive_data_no_hits():
    """回归：无敏感数据的 MCP 事件不误报。"""
    record = {
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "call_id": "call_clean_1",
            "duration": {"nanos": 1000000, "secs": 0},
            "invocation": {
                "server": "node_repl",
                "tool": "js",
                "arguments": {"code": "console.log('hello world')", "timeout_ms": 5000},
            },
            "result": {"Ok": {"content": [{"text": "hello world", "type": "text"}], "isError": False}},
        },
    }
    fact = _tool_fact(_common(), record)
    assert fact is not None

    projection_json = json.dumps(fact["projection"], ensure_ascii=False, sort_keys=True, default=str)
    raw_content = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)

    matches = detect_for_fact(projection_json, raw_content)
    # 不应有 token / secret / cookie 等凭据类别命中
    credential_cats = {"token", "secret", "cookie", "auth"}
    hit_cats = {m["category"] for m in matches}
    assert not (hit_cats & credential_cats), f"无敏感数据但命中凭据类别: {hit_cats & credential_cats}"
