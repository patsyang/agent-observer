"""MCP 工具调用查询服务。

查询 evidence_projections 中 projection_json 含 mcp_server 字段的记录，
JOIN observed_facts 取时间与会话引用，LEFT JOIN risk_signals 取关联风险信号。
"""
from __future__ import annotations

import json
import sqlite3


def _fetch_risk_signals(conn: sqlite3.Connection, fact_ids: list[str]) -> dict[str, list[str]]:
    """按 fact_id 批量取关联的 risk_type 列表。"""
    if not fact_ids:
        return {}
    placeholders = ",".join("?" * len(fact_ids))
    rows = conn.execute(
        f"select distinct fact_id, risk_type from risk_signals where fact_id in ({placeholders})",
        fact_ids,
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["fact_id"], []).append(row["risk_type"])
    return result


def list_mcp_calls(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    page_size: int = 50,
    server: str | None = None,
    risk_only: bool = False,
) -> dict:
    """查询 MCP 工具调用记录。

    筛选策略：
      - SQL 层用 projection_json LIKE '%"mcp_server"%' 收窄候选集
      - risk_only=True 时追加 EXISTS risk_signals 子查询
      - server 在 Python 层过滤（projection 解析后精确匹配）
    返回 items + 分页信息 + summary（servers/total_calls/error_calls/risk_calls）。
    summary 反映筛选后、分页前的集合。
    """
    sql = (
        "select ep.fact_id, ep.projection_json, of.occurred_at, of.conversation_ref "
        "from evidence_projections ep "
        "join observed_facts of on ep.fact_id = of.fact_id "
        "where ep.projection_json like '%\"mcp_server\"%'"
    )
    if risk_only:
        sql += " and exists (select 1 from risk_signals rs where rs.fact_id = ep.fact_id)"
    sql += " order by of.occurred_at desc"

    rows = conn.execute(sql).fetchall()

    parsed: list[dict] = []
    for row in rows:
        try:
            projection = json.loads(row["projection_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(projection, dict):
            continue
        if "mcp_server" not in projection:
            continue
        if server is not None and projection.get("mcp_server") != server:
            continue
        parsed.append({
            "fact_id": row["fact_id"],
            "occurred_at": row["occurred_at"],
            "conversation_ref": row["conversation_ref"],
            "projection": projection,
        })

    risk_map = _fetch_risk_signals(conn, [p["fact_id"] for p in parsed])
    servers = sorted({p["projection"]["mcp_server"] for p in parsed})
    total_calls = len(parsed)
    error_calls = sum(1 for p in parsed if p["projection"].get("mcp_is_error"))
    risk_calls = sum(1 for p in parsed if risk_map.get(p["fact_id"]))

    start = (page - 1) * page_size
    page_items = parsed[start : start + page_size]

    items = []
    for p in page_items:
        proj = p["projection"]
        items.append({
            "fact_id": p["fact_id"],
            "occurred_at": p["occurred_at"],
            "conversation_ref": p["conversation_ref"],
            "mcp_server": proj.get("mcp_server"),
            "mcp_tool": proj.get("mcp_tool"),
            "mcp_duration_ms": proj.get("mcp_duration_ms"),
            "mcp_is_error": proj.get("mcp_is_error", False),
            "argument_keys": proj.get("argument_keys", []),
            "risk_signals": risk_map.get(p["fact_id"], []),
        })

    return {
        "items": items,
        "total": total_calls,
        "page": page,
        "page_size": page_size,
        "summary": {
            "servers": servers,
            "total_calls": total_calls,
            "error_calls": error_calls,
            "risk_calls": risk_calls,
        },
    }
