"""MCP 上下文字段透传测试。

验证 _items() 和 _hit_dict() 正确从 projection 中提取 mcp_server/mcp_tool/
mcp_duration_ms/mcp_is_error 字段，透传到 API 响应。
"""
from __future__ import annotations

import json
import sqlite3

from app.behavior_signals.helpers import _items
from app.conversations.service import _hit_dict


# ---------------------------------------------------------------------------
# _items() 测试：验证 behavior_signals/helpers.py 透传 mcp 字段
# ---------------------------------------------------------------------------

def _create_items_db() -> sqlite3.Connection:
    """内存 DB：observed_facts + evidence_projections（空），供 _items/evidence_entries 使用。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table observed_facts (
            fact_id text primary key,
            category text not null default '',
            quality text not null default '',
            fact_type text not null default '',
            occurred_at text not null default '',
            summary text not null default '',
            conversation_ref text not null default '',
            content_preview text not null default '',
            source_refs_json text not null default '{}',
            source_specific_json text not null default '{}'
        )
        """
    )
    conn.execute(
        """
        create table evidence_projections (
            projection_id text primary key,
            fact_id text not null,
            projection_json text not null
        )
        """
    )
    conn.commit()
    return conn


def _insert_fact(conn: sqlite3.Connection, fact_id: str = "fact-1") -> sqlite3.Row:
    conn.execute(
        "insert into observed_facts (fact_id, category, quality, fact_type, occurred_at, "
        "summary, conversation_ref, content_preview, source_refs_json, source_specific_json) "
        "values (?, 'tool', 'high', 'tool', '2026-07-12T10:00:00+00:00', "
        "'MCP tool call', 'conv-1', 'preview', '{}', '{}')",
        (fact_id,),
    )
    conn.commit()
    return conn.execute("select * from observed_facts where fact_id = ?", (fact_id,)).fetchone()


def test_items_returns_mcp_fields_when_projection_has_mcp_server():
    """_items() 对包含 mcp_server 的 projection 返回 mcp 字段。"""
    conn = _create_items_db()
    fact = _insert_fact(conn, "fact-mcp")
    projection = {
        "mcp_server": "node_repl",
        "mcp_tool": "js",
        "mcp_duration_ms": 5,
        "mcp_is_error": False,
        "tool_name": "js",
    }
    items = _items(conn, [fact], [projection])

    assert len(items) == 1
    item = items[0]
    assert item["mcp_server"] == "node_repl"
    assert item["mcp_tool"] == "js"
    assert item["mcp_duration_ms"] == 5
    assert item["mcp_is_error"] is False


def test_items_returns_none_mcp_fields_when_projection_has_no_mcp_server():
    """_items() 对无 mcp_server 的 projection 返回 mcp_server=None。"""
    conn = _create_items_db()
    fact = _insert_fact(conn, "fact-no-mcp")
    projection = {"tool_name": "edit", "exit_code": 0}

    items = _items(conn, [fact], [projection])

    assert len(items) == 1
    item = items[0]
    assert item["mcp_server"] is None
    assert item["mcp_tool"] is None
    assert item["mcp_duration_ms"] is None
    assert item["mcp_is_error"] is None


# ---------------------------------------------------------------------------
# _hit_dict() 测试：验证 conversations/service.py 透传 mcp 字段
# ---------------------------------------------------------------------------

def _make_hit_row(projection_json: str | None) -> sqlite3.Row:
    """构造一个包含 projection_json 列的 sqlite3.Row，模拟 LEFT JOIN 后的查询结果。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table hit_mock (
            fact_id text, category text, fact_type text, severity text,
            occurred_at text, summary text, content_preview text,
            tool_context_json text, sensitive_matches_json text, source_line text,
            projection_json text
        )
        """
    )
    conn.execute(
        "insert into hit_mock values "
        "('fact-1', 'tool_call', 'tool', 'low', '2026-07-12T10:00:00+00:00', "
        "'MCP call', 'preview', null, '[]', null, ?)",
        (projection_json,),
    )
    return conn.execute("select * from hit_mock").fetchone()


def test_hit_dict_returns_mcp_fields_when_projection_has_mcp_server():
    """_hit_dict() 对包含 mcp_server 的 projection 返回 mcp 字段。"""
    projection = json.dumps({
        "mcp_server": "filesystem",
        "mcp_tool": "read_file",
        "mcp_duration_ms": 12,
        "mcp_is_error": True,
    })
    row = _make_hit_row(projection)

    result = _hit_dict(row)

    assert result["mcp_server"] == "filesystem"
    assert result["mcp_tool"] == "read_file"
    assert result["mcp_duration_ms"] == 12
    assert result["mcp_is_error"] is True


def test_hit_dict_returns_none_mcp_fields_when_projection_has_no_mcp_server():
    """_hit_dict() 对无 mcp_server 的 projection 返回 mcp_server=None。"""
    projection = json.dumps({"tool_name": "edit"})
    row = _make_hit_row(projection)

    result = _hit_dict(row)

    assert result["mcp_server"] is None
    assert result["mcp_tool"] is None
    assert result["mcp_duration_ms"] is None
    assert result["mcp_is_error"] is None
