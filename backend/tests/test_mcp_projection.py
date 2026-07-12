"""fact_mapper._tool_fact() 对 MCP 事件（mcp_tool_call_end）的 projection 提取。

MCP 事件原始结构：
    {
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "call_id": "call_xxx",
            "duration": {"nanos": 5382700, "secs": 0},
            "invocation": {
                "server": "node_repl",
                "tool": "js",
                "arguments": {"code": "console.log('hello')", "timeout_ms": 30000},
            },
            "result": {"Ok": {"content": [...], "isError": false}},
        },
    }

期望 projection 追加 mcp_server / mcp_tool / mcp_duration_ms / mcp_is_error，
且 tool_name 取实际工具名（invocation.tool）而非 payload.type。
"""
from __future__ import annotations

import json

from app.collector_client.fact_mapper import _tool_fact


def _common() -> dict:
    """构造 _tool_fact 所需的最小 common dict。"""
    return {
        "source_event_id": "evt-mcp-1",
        "occurred_at": "2026-07-12T10:00:00+00:00",
        "span": "codex-session:mcp-test",
        "raw_hash": "rawhash0001",
        "source_refs": {"conversation_ref": "ref:conv1", "session_ref": "ref:sess1"},
        "source_specific": {"event_type": "event_msg:mcp_tool_call_end"},
        "upload_raw": True,
        "raw_content": "{}",
    }


def _mcp_record(
    *,
    invocation: dict | None = None,
    duration: dict | None = None,
    result: dict | None = None,
) -> dict:
    """构造 MCP 事件 record。"""
    payload: dict = {"type": "mcp_tool_call_end", "call_id": "call_mcp_1"}
    if invocation is not None:
        payload["invocation"] = invocation
    if duration is not None:
        payload["duration"] = duration
    if result is not None:
        payload["result"] = result
    return {"type": "event_msg", "payload": payload}


def _ok_result() -> dict:
    return {"Ok": {"content": [{"text": "hello", "type": "text"}], "isError": False}}


def _err_result() -> dict:
    return {"Err": {"code": "tool_failed", "message": "execution error"}}


def _default_invocation() -> dict:
    return {
        "server": "node_repl",
        "tool": "js",
        "arguments": {"code": "console.log('hello')", "timeout_ms": 30000},
    }


def test_mcp_projection_includes_mcp_fields():
    """MCP 事件 projection 包含 mcp_server/mcp_tool/mcp_duration_ms/mcp_is_error。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 5382700, "secs": 0},
        result=_ok_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    projection = fact["projection"]
    assert projection["mcp_server"] == "node_repl"
    assert projection["mcp_tool"] == "js"
    assert projection["mcp_duration_ms"] == 5  # 5382700 nanos ≈ 5.38 ms → 5
    assert projection["mcp_is_error"] is False


def test_mcp_tool_name_uses_invocation_tool_not_payload_type():
    """tool_name 取 invocation.tool='js'，而非 payload.type='mcp_tool_call_end'。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 5382700, "secs": 0},
        result=_ok_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["tool_name"] == "js"


def test_mcp_event_without_invocation_has_no_mcp_fields():
    """MCP 事件无 invocation 字段时 projection 不包含 MCP 字段。"""
    record = _mcp_record(duration={"nanos": 1000000, "secs": 0}, result=_ok_result())
    fact = _tool_fact(_common(), record)
    assert fact is not None
    projection = fact["projection"]
    assert "mcp_server" not in projection
    assert "mcp_tool" not in projection
    assert "mcp_duration_ms" not in projection
    assert "mcp_is_error" not in projection


def test_mcp_event_without_duration_has_zero_duration_ms():
    """MCP 事件无 duration 字段时 mcp_duration_ms=0。"""
    record = _mcp_record(invocation=_default_invocation(), result=_ok_result())
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_duration_ms"] == 0


def test_mcp_event_with_err_result_sets_is_error_true():
    """MCP 事件 result.Err 时 mcp_is_error=True。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 2000000, "secs": 0},
        result=_err_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_is_error"] is True


def test_mcp_event_with_ok_result_is_error_false():
    """MCP 事件 result.Ok 且 isError=false 时 mcp_is_error=False。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 2000000, "secs": 0},
        result=_ok_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_is_error"] is False


def test_mcp_event_with_ok_result_is_error_true():
    """MCP 事件 result.Ok 但 isError=true 时 mcp_is_error=True。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 2000000, "secs": 0},
        result={"Ok": {"content": [{"text": "err", "type": "text"}], "isError": True}},
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_is_error"] is True


def test_mcp_event_without_result_is_error_false():
    """MCP 事件无 result 字段时 mcp_is_error=False（缺省非错误）。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 2000000, "secs": 0},
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_is_error"] is False


def test_mcp_event_duration_with_secs_only():
    """duration 仅含 secs 时 mcp_duration_ms = secs * 1000。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 0, "secs": 2},
        result=_ok_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_duration_ms"] == 2000


def test_mcp_event_argument_keys_extracted_from_invocation():
    """MCP 事件 argument_keys 从 invocation.arguments 提取（依赖 Task 1 的 arguments() 回退）。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 1000000, "secs": 0},
        result=_ok_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    projection = fact["projection"]
    assert "code" in projection["argument_keys"]
    assert "timeout_ms" in projection["argument_keys"]


def test_mcp_event_raw_content_uploaded_preserved():
    """MCP 事件仍保留 raw_content_uploaded 字段。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 1000000, "secs": 0},
        result=_ok_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["raw_content_uploaded"] is True


def test_mcp_projection_includes_args_summary():
    """MCP 事件 projection 包含 mcp_args_summary，取 code 首行。"""
    record = _mcp_record(
        invocation=_default_invocation(),
        duration={"nanos": 1000000, "secs": 0},
        result=_ok_result(),
    )
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_args_summary"] == "console.log('hello')"


def test_mcp_projection_args_summary_uses_title_when_present():
    """arguments 含 title 时 mcp_args_summary 取 title。"""
    invocation = {
        "server": "node_repl",
        "tool": "js",
        "arguments": {"code": "console.log('x')", "title": "测试操作"},
    }
    record = _mcp_record(invocation=invocation, duration={"nanos": 1000000, "secs": 0}, result=_ok_result())
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["mcp_args_summary"] == "测试操作"
