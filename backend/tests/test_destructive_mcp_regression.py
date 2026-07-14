"""破坏性命令回归测试：验证 MCP 事件经 _tool_fact 处理后的 fact_type 分类。

MCP 事件含 cmd="rm -rf ..." 时，_tool_fact 自身不做破坏性分类（始终返回 fact_type="tool"）。
破坏性检测由 _destructive_fact 在 _record_fact 管线中更早负责。
非破坏性 MCP 事件（如 console.log）同样返回 fact_type="tool"。
"""
from __future__ import annotations

from app.collector_client.fact_mapper import _destructive_fact, _tool_fact


def _common() -> dict:
    return {
        "source_event_id": "evt-mcp-destructive-1",
        "occurred_at": "2026-07-12T10:00:00+00:00",
        "span": "codex-session:mcp-destructive",
        "raw_hash": "rawhashdestructive01",
        "source_refs": {"conversation_ref": "ref:conv1", "session_ref": "ref:sess1"},
        "source_specific": {"event_type": "event_msg:mcp_tool_call_end"},
        "upload_raw": True,
        "raw_content": "{}",
    }


def _mcp_record_with_cmd(cmd: str) -> dict:
    """MCP 事件，invocation.arguments 中包含 cmd 字段。"""
    return {
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "call_id": "call_destructive_1",
            "duration": {"nanos": 2000000, "secs": 0},
            "invocation": {
                "server": "shell_server",
                "tool": "bash",
                "arguments": {"cmd": cmd},
            },
            "result": {"Ok": {"content": [{"text": "done", "type": "text"}], "isError": False}},
        },
    }


def _mcp_record_with_code(code: str) -> dict:
    """MCP 事件，invocation.arguments 中包含 code 字段（非破坏性 JS 代码）。"""
    return {
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "call_id": "call_code_1",
            "duration": {"nanos": 1500000, "secs": 0},
            "invocation": {
                "server": "node_repl",
                "tool": "js",
                "arguments": {"code": code, "timeout_ms": 5000},
            },
            "result": {"Ok": {"content": [{"text": "ok", "type": "text"}], "isError": False}},
        },
    }


def test_mcp_event_with_rm_rf_cmd_tool_fact_not_destructive():
    """MCP 事件 cmd='rm -rf /tmp/test' 经 _tool_fact 处理后 fact_type='tool'，不是 'destructive_operation'。

    _tool_fact 不做破坏性分类；破坏性检测由 _destructive_fact 在 _record_fact 管线中负责。
    """
    record = _mcp_record_with_cmd("rm -rf /tmp/test")
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["fact_type"] == "tool"
    assert fact["category"] == "tool_call"
    assert fact["fact_type"] != "destructive_operation"


def test_mcp_event_with_rm_rf_cmd_command_category_destructive():
    """MCP 事件 cmd='rm -rf /tmp/test' 的 command_category 仍为 'destructive'（projection 中可见）。

    这验证 Task 1 的 arguments() 回退使 command_text 能提取 MCP 事件的 cmd，
    command_category 正确识别为 destructive。
    """
    record = _mcp_record_with_cmd("rm -rf /tmp/test")
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["command"] == "rm -rf /tmp/test"
    assert fact["projection"]["command_category"] == "destructive"


def test_mcp_event_with_rm_rf_destructive_fact_catches_it():
    """MCP 事件 cmd='rm -rf /tmp/test' 被 _destructive_fact 捕获为破坏性操作。

    依赖 Task 1 的 arguments() 回退：_destructive_fact 调用 _arguments(payload) 能
    提取 invocation.arguments.cmd，command_category='destructive' 命中。
    """
    record = _mcp_record_with_cmd("rm -rf /tmp/test")
    destructive = _destructive_fact(_common(), record)
    assert destructive is not None
    assert destructive["fact_type"] == "risk"
    assert destructive["category"] == "destructive_operation"


def test_mcp_event_with_console_log_not_destructive():
    """MCP 事件 arguments={code: 'console.log(...)'} 不命中破坏性分类。"""
    record = _mcp_record_with_code("console.log('hello')")
    # _tool_fact 返回普通 tool fact
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["fact_type"] == "tool"
    assert fact["fact_type"] != "destructive_operation"

    # _destructive_fact 不命中（command 为空，operation 不在 DESTRUCTIVE_OPERATIONS）
    destructive = _destructive_fact(_common(), record)
    assert destructive is None


def test_mcp_event_with_console_log_command_category_empty():
    """MCP 事件 code='console.log(...)' 的 command 为空（command_text 只看 cmd/command）。"""
    record = _mcp_record_with_code("console.log('hello')")
    fact = _tool_fact(_common(), record)
    assert fact is not None
    assert fact["projection"]["command"] == ""
    assert fact["projection"]["command_category"] == ""


def _record_with_path(command: str, path: str) -> dict:
    """构造一个带 path 字段的 function_call record（用于测试 path 中的关键词匹配）。"""
    return {
        "type": "response_item",
        "path": path,
        "payload": {
            "type": "function_call",
            "name": "shell_command",
            "call_id": "call_path_test_1",
            "arguments": {"command": command},
        },
    }


def test_path_with_undelete_word_not_destructive():
    """path 中包含 'undelete'（无词边界）不应触发破坏性 fact。

    回归：旧逻辑用 ``"delete" not in path`` 子串匹配，会把 'undelete' 中的
    'delete' 子串误判为删除操作路径。新逻辑用 ``\\bdelet(e|ion)\\b`` 词边界正则，
    'undelete' 中 'delete' 前无词边界，不匹配。
    """
    record = _record_with_path(
        command="python D:/workspace/undelete_recovery.py",
        path="D:/workspace/undelete_recovery.py",
    )
    destructive = _destructive_fact(_common(), record)
    assert destructive is None, (
        "path 含 'undelete'（无词边界）不应触发破坏性 fact"
    )


def test_path_with_deletion_word_still_destructive():
    """path 中包含 'deletion'（有词边界）仍应触发破坏性 fact。

    确保词边界正则不会漏掉真正的 'deletion' 关键词。
    使用 'deletion.log'（点号是非单词字符，形成词边界）。
    """
    record = _record_with_path(
        command="ls D:/workspace/deletion.log",
        path="D:/workspace/deletion.log",
    )
    destructive = _destructive_fact(_common(), record)
    assert destructive is not None, (
        "path 含 'deletion'（有词边界）应触发破坏性 fact"
    )
    assert destructive["fact_type"] == "risk"
    assert destructive["category"] == "destructive_operation"
