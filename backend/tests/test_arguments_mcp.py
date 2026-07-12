"""telemetry_utils.arguments() 对 MCP 事件 payload.invocation.arguments 的回退提取。

MCP 事件结构：
    payload = {
        "type": "mcp_tool_call_end",
        "invocation": {
            "server": "node_repl",
            "tool": "js",
            "arguments": {"code": "console.log('hi')", "timeout_ms": 30000},
        },
    }
payload.arguments 和 payload.input 都为空时，需回退查 payload.invocation.arguments。
"""
from __future__ import annotations

from app.collector_client.telemetry_utils import arguments


def test_arguments_falls_back_to_invocation_arguments_for_mcp_event():
    """MCP 事件：payload.arguments / payload.input 均空，回退 payload.invocation.arguments。"""
    payload = {
        "type": "mcp_tool_call_end",
        "call_id": "call_mcp_1",
        "invocation": {
            "server": "node_repl",
            "tool": "js",
            "arguments": {"code": "console.log('hello')", "timeout_ms": 30000},
        },
    }
    result = arguments(payload)
    assert result == {"code": "console.log('hello')", "timeout_ms": 30000}


def test_arguments_prefers_payload_arguments_when_present():
    """非 MCP 事件：payload.arguments 优先于 invocation.arguments。"""
    payload = {
        "type": "function_call",
        "arguments": {"cmd": "git status"},
        "invocation": {"arguments": {"cmd": "rm -rf /"}},
    }
    result = arguments(payload)
    assert result == {"cmd": "git status"}


def test_arguments_prefers_payload_input_when_arguments_empty():
    """非 MCP 事件：payload.input 优先于 invocation.arguments（arguments 为空时）。"""
    payload = {
        "type": "custom_tool_call",
        "input": {"path": "/tmp/x"},
        "invocation": {"arguments": {"path": "/tmp/y"}},
    }
    result = arguments(payload)
    assert result == {"path": "/tmp/x"}


def test_arguments_returns_empty_when_invocation_is_none():
    """payload.invocation 为 None 时不崩溃，返回 {}。"""
    payload = {"type": "mcp_tool_call_end", "invocation": None}
    result = arguments(payload)
    assert result == {}


def test_arguments_returns_empty_when_invocation_arguments_not_dict():
    """payload.invocation.arguments 为非 dict（如字符串、列表）时返回 {}。"""
    payload = {
        "type": "mcp_tool_call_end",
        "invocation": {"server": "node_repl", "tool": "js", "arguments": "not a dict"},
    }
    result = arguments(payload)
    assert result == {}


def test_arguments_returns_empty_when_invocation_arguments_is_none():
    """payload.invocation.arguments 为 None 时返回 {}。"""
    payload = {
        "type": "mcp_tool_call_end",
        "invocation": {"server": "node_repl", "tool": "js", "arguments": None},
    }
    result = arguments(payload)
    assert result == {}


def test_arguments_unchanged_for_legacy_payload_without_invocation():
    """回归：没有 invocation 字段的传统事件行为不变。"""
    payload = {"type": "function_call", "arguments": {"cmd": "ls -la"}}
    assert arguments(payload) == {"cmd": "ls -la"}

    payload_input = {"type": "custom_tool_call", "input": {"cmd": "dir"}}
    assert arguments(payload_input) == {"cmd": "dir"}

    payload_empty = {"type": "function_call"}
    assert arguments(payload_empty) == {}


def test_arguments_invocation_not_dict_returns_empty():
    """payload.invocation 非 dict（如字符串）时返回 {}，不崩溃。"""
    payload = {"type": "mcp_tool_call_end", "invocation": "unexpected string"}
    result = arguments(payload)
    assert result == {}


def test_arguments_invocation_arguments_json_string_parsed():
    """payload.invocation.arguments 是 JSON 字符串时按现有 str 分支解析。

    复用 arguments() 现有逻辑：str 以 '{' 开头则 json.loads。
    """
    payload = {
        "type": "mcp_tool_call_end",
        "invocation": {
            "arguments": '{"code": "console.log(1)", "timeout_ms": 5000}',
        },
    }
    result = arguments(payload)
    assert result == {"code": "console.log(1)", "timeout_ms": 5000}
