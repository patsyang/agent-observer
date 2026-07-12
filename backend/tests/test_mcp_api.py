"""MCP 查询 API 的 service 层测试（Task 5）。

覆盖场景：
1. list_mcp_calls 只返回 MCP 记录，不含非 MCP
2. server 筛选只返回匹配 mcp_server 的记录
3. risk_only=True 只返回有关联 risk_signal 的记录
4. summary 包含 servers / total_calls / error_calls / risk_calls
5. 分页、排序、item 字段、risk_signals 关联
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.mcp.service import list_mcp_calls


def _create_test_db() -> sqlite3.Connection:
    """建内存 SQLite，只包含 service 查询涉及的最小列。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table observed_facts (
            fact_id text primary key,
            occurred_at text not null,
            conversation_ref text not null default ''
        )
        """
    )
    conn.execute(
        """
        create table evidence_projections (
            projection_id text primary key,
            fact_id text not null,
            projection_json text not null,
            raw_content text
        )
        """
    )
    conn.execute(
        """
        create table risk_signals (
            signal_id text primary key,
            fact_id text not null,
            risk_type text not null
        )
        """
    )
    conn.commit()
    return conn


def _insert_fact(conn: sqlite3.Connection, fact_id: str, occurred_at: str, conversation_ref: str = "ref:conv1") -> None:
    conn.execute(
        "insert into observed_facts (fact_id, occurred_at, conversation_ref) values (?, ?, ?)",
        (fact_id, occurred_at, conversation_ref),
    )


def _insert_projection(conn: sqlite3.Connection, fact_id: str, projection: dict, projection_id: str | None = None, raw_content: str | None = None) -> None:
    pid = projection_id or f"proj-{fact_id}"
    conn.execute(
        "insert into evidence_projections (projection_id, fact_id, projection_json, raw_content) values (?, ?, ?, ?)",
        (pid, fact_id, json.dumps(projection), raw_content),
    )


def _insert_risk(conn: sqlite3.Connection, fact_id: str, risk_type: str, signal_id: str | None = None) -> None:
    sid = signal_id or f"risk:{fact_id}:{risk_type}"
    conn.execute(
        "insert into risk_signals (signal_id, fact_id, risk_type) values (?, ?, ?)",
        (sid, fact_id, risk_type),
    )


def _mcp_projection(
    *,
    server: str = "node_repl",
    tool: str = "js",
    duration_ms: int = 5,
    is_error: bool = False,
    argument_keys: list[str] | None = None,
    args_summary: str = "",
) -> dict:
    return {
        "tool_name": tool,
        "mcp_server": server,
        "mcp_tool": tool,
        "mcp_duration_ms": duration_ms,
        "mcp_is_error": is_error,
        "argument_keys": argument_keys if argument_keys is not None else ["code"],
        "mcp_args_summary": args_summary,
    }


@pytest.fixture
def db_with_mcp_records() -> sqlite3.Connection:
    """3 条 MCP + 1 条非 MCP，其中 2 条 MCP 有关联 risk_signal。"""
    conn = _create_test_db()

    # MCP 1: node_repl/js, 无 risk
    _insert_fact(conn, "fact-mcp-1", "2026-07-12T10:00:00+00:00", "ref:conv1")
    _insert_projection(conn, "fact-mcp-1", _mcp_projection(
        server="node_repl", tool="js", duration_ms=5, is_error=False,
        argument_keys=["code", "timeout_ms"], args_summary="console.log('hello')",
    ), raw_content=json.dumps({"payload": {"invocation": {"arguments": {"code": "console.log('hello')"}}, "result": {"Ok": {"content": [{"text": "hello", "type": "text"}], "isError": False}}}}))

    # MCP 2: filesystem/read_file, 有 risk + error
    _insert_fact(conn, "fact-mcp-2", "2026-07-12T11:00:00+00:00", "ref:conv2")
    _insert_projection(conn, "fact-mcp-2", _mcp_projection(
        server="filesystem", tool="read_file", duration_ms=12, is_error=True,
        argument_keys=["path"], args_summary="/etc/config.yaml",
    ), raw_content=json.dumps({"payload": {"invocation": {"arguments": {"path": "/etc/config.yaml"}}, "result": {"Err": "permission denied"}}}))
    _insert_risk(conn, "fact-mcp-2", "sensitive_content_exposure")

    # MCP 3: node_repl/exec, 有 risk
    _insert_fact(conn, "fact-mcp-3", "2026-07-12T12:00:00+00:00", "ref:conv3")
    _insert_projection(conn, "fact-mcp-3", _mcp_projection(
        server="node_repl", tool="exec", duration_ms=8, is_error=False,
        argument_keys=["cmd"], args_summary="rm -rf /tmp/cache",
    ), raw_content=json.dumps({"payload": {"invocation": {"arguments": {"cmd": "rm -rf /tmp/cache"}}, "result": {"Ok": {"content": [{"text": "done", "type": "text"}], "isError": False}}}}))
    _insert_risk(conn, "fact-mcp-3", "destructive_operation")

    # 非 MCP 记录：projection 不含 mcp_server
    _insert_fact(conn, "fact-non-mcp-1", "2026-07-12T09:00:00+00:00", "ref:conv1")
    _insert_projection(conn, "fact-non-mcp-1", {"tool_name": "edit", "argument_keys": []})

    conn.commit()
    return conn


class TestListMcpCalls:
    """list_mcp_calls 行为测试。"""

    def test_returns_only_mcp_records_excludes_non_mcp(self, db_with_mcp_records):
        """只返回 MCP 记录，不含非 MCP。"""
        result = list_mcp_calls(db_with_mcp_records, page=1, page_size=50)
        fact_ids = {item["fact_id"] for item in result["items"]}
        assert "fact-mcp-1" in fact_ids
        assert "fact-mcp-2" in fact_ids
        assert "fact-mcp-3" in fact_ids
        assert "fact-non-mcp-1" not in fact_ids

    def test_returns_expected_item_fields(self, db_with_mcp_records):
        """item 包含 occurred_at/conversation_ref/mcp_server/mcp_tool 等字段。"""
        result = list_mcp_calls(db_with_mcp_records, page=1, page_size=50)
        item = next(i for i in result["items"] if i["fact_id"] == "fact-mcp-1")
        assert item["occurred_at"] == "2026-07-12T10:00:00+00:00"
        assert item["conversation_ref"] == "ref:conv1"
        assert item["mcp_server"] == "node_repl"
        assert item["mcp_tool"] == "js"
        assert item["mcp_duration_ms"] == 5
        assert item["mcp_is_error"] is False
        assert item["mcp_args_summary"] == "console.log('hello')"
        assert any(a["key"] == "code" for a in item["arguments"])
        assert item["result_text"] == "hello"
        assert item["risk_signals"] == []

    def test_filter_by_server_node_repl(self, db_with_mcp_records):
        """server=node_repl 只返回该 server 的记录。"""
        result = list_mcp_calls(db_with_mcp_records, server="node_repl")
        fact_ids = {item["fact_id"] for item in result["items"]}
        assert fact_ids == {"fact-mcp-1", "fact-mcp-3"}
        assert all(item["mcp_server"] == "node_repl" for item in result["items"])

    def test_filter_by_server_filesystem(self, db_with_mcp_records):
        """server=filesystem 只返回该 server 的记录。"""
        result = list_mcp_calls(db_with_mcp_records, server="filesystem")
        fact_ids = {item["fact_id"] for item in result["items"]}
        assert fact_ids == {"fact-mcp-2"}

    def test_risk_only_filter(self, db_with_mcp_records):
        """risk_only=True 只返回有关联 risk_signal 的记录。"""
        result = list_mcp_calls(db_with_mcp_records, risk_only=True)
        fact_ids = {item["fact_id"] for item in result["items"]}
        assert fact_ids == {"fact-mcp-2", "fact-mcp-3"}

    def test_risk_signals_attached_to_items(self, db_with_mcp_records):
        """item 的 risk_signals 字段包含关联的 risk_type 列表。"""
        result = list_mcp_calls(db_with_mcp_records, page=1, page_size=50)
        item2 = next(i for i in result["items"] if i["fact_id"] == "fact-mcp-2")
        assert "sensitive_content_exposure" in item2["risk_signals"]
        item3 = next(i for i in result["items"] if i["fact_id"] == "fact-mcp-3")
        assert "destructive_operation" in item3["risk_signals"]

    def test_summary_contains_required_fields(self, db_with_mcp_records):
        """summary 包含 servers/total_calls/error_calls/risk_calls。"""
        result = list_mcp_calls(db_with_mcp_records, page=1, page_size=50)
        summary = result["summary"]
        assert set(summary.keys()) == {"servers", "total_calls", "error_calls", "risk_calls"}
        assert set(summary["servers"]) == {"node_repl", "filesystem"}
        assert summary["total_calls"] == 3
        assert summary["error_calls"] == 1
        assert summary["risk_calls"] == 2

    def test_summary_reflects_server_filter(self, db_with_mcp_records):
        """server 筛选后 summary 反映筛选后的集合。"""
        result = list_mcp_calls(db_with_mcp_records, server="node_repl")
        summary = result["summary"]
        assert summary["servers"] == ["node_repl"]
        assert summary["total_calls"] == 2
        assert summary["error_calls"] == 0
        assert summary["risk_calls"] == 1

    def test_pagination_first_page(self, db_with_mcp_records):
        """分页：page=1, page_size=2 返回 2 条，total=3。"""
        result = list_mcp_calls(db_with_mcp_records, page=1, page_size=2)
        assert len(result["items"]) == 2
        assert result["total"] == 3
        assert result["page"] == 1
        assert result["page_size"] == 2

    def test_pagination_second_page(self, db_with_mcp_records):
        """分页：page=2, page_size=2 返回剩余 1 条。"""
        result = list_mcp_calls(db_with_mcp_records, page=2, page_size=2)
        assert len(result["items"]) == 1
        assert result["total"] == 3

    def test_ordered_by_occurred_at_desc(self, db_with_mcp_records):
        """结果按 occurred_at 降序排列。"""
        result = list_mcp_calls(db_with_mcp_records, page=1, page_size=50)
        occurred = [item["occurred_at"] for item in result["items"]]
        assert occurred == sorted(occurred, reverse=True)
        assert occurred[0] == "2026-07-12T12:00:00+00:00"

    def test_empty_db_returns_empty_items(self):
        """空数据库返回空 items 和零值 summary。"""
        conn = _create_test_db()
        result = list_mcp_calls(conn)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["summary"]["servers"] == []
        assert result["summary"]["total_calls"] == 0
        assert result["summary"]["error_calls"] == 0
        assert result["summary"]["risk_calls"] == 0
