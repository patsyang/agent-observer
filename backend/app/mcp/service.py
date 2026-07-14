"""MCP 工具调用查询服务。

查询 evidence_projections 中 projection_json 含 mcp_server 字段的记录，
JOIN observed_facts 取时间与会话引用，LEFT JOIN risk_signals 取关联风险信号。
"""
from __future__ import annotations

import json
import sqlite3


_MAX_RESULT_TEXT = 500


def _fetch_risk_signals(conn: sqlite3.Connection, fact_ids: list[str]) -> dict[str, list[dict]]:
    """按 fact_id 批量取关联的风险信号（risk_type + severity + object_type）。"""
    if not fact_ids:
        return {}
    placeholders = ",".join("?" * len(fact_ids))
    rows = conn.execute(
        f"select distinct fact_id, risk_type, severity, object_type from risk_signals where fact_id in ({placeholders})",
        fact_ids,
    ).fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        result.setdefault(row["fact_id"], []).append({
            "risk_type": row["risk_type"],
            "severity": row["severity"],
            "object_type": row["object_type"],
        })
    return result


def _extract_detail(raw_content: str | None) -> tuple[list[dict], str]:
    """从 raw_content 解析 MCP 调用的参数和结果摘要。

    返回 (arguments_list, result_text)。
    arguments_list 格式: [{"key": "code", "value": "..."}, ...]
    result_text: result.Ok.content 的文本拼接，截断到 _MAX_RESULT_TEXT 字符。
    """
    if not raw_content:
        return [], ""
    try:
        raw = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError):
        return [], ""
    payload = raw.get("payload", {}) if isinstance(raw, dict) else {}
    if not isinstance(payload, dict):
        return [], ""

    invocation = payload.get("invocation", {})
    args_list: list[dict] = []
    if isinstance(invocation, dict):
        args = invocation.get("arguments")
        if isinstance(args, dict):
            for k, v in args.items():
                args_list.append({"key": k, "value": str(v) if not isinstance(v, str) else v})

    result_text = ""
    result = payload.get("result")
    if isinstance(result, dict):
        ok = result.get("Ok")
        if isinstance(ok, dict):
            content = ok.get("content", [])
            if isinstance(content, list):
                parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                result_text = "\n".join(parts)[:_MAX_RESULT_TEXT]
        elif "Err" in result:
            err = result["Err"]
            result_text = str(err)[:_MAX_RESULT_TEXT]

    return args_list, result_text


def list_mcp_calls(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    page_size: int = 50,
    server: str | None = None,
    risk_only: bool = False,
    error_only: bool = False,
) -> dict:
    """查询 MCP 工具调用记录。

    筛选和分页全部在 SQL 层完成：
      - json_extract 在 SQL 层过滤 mcp_server / mcp_is_error
      - LIMIT/OFFSET 只加载当前页的 raw_content
      - summary 用聚合查询，不加载 raw_content
    """
    where_clauses = ["ep.projection_json like '%\"mcp_server\"%'"]
    params: list = []
    if server:
        where_clauses.append("json_extract(ep.projection_json, '$.mcp_server') = ?")
        params.append(server)
    if error_only:
        where_clauses.append("json_extract(ep.projection_json, '$.mcp_is_error') = 1")
    if risk_only:
        where_clauses.append("exists (select 1 from risk_signals rs where rs.fact_id = ep.fact_id)")
    where = "where " + " and ".join(where_clauses)
    join = "from evidence_projections ep join observed_facts of on ep.fact_id = of.fact_id"

    # 1. Summary（轻量聚合，不加载 raw_content）
    total = conn.execute(f"select count(*) {join} {where}", params).fetchone()[0]

    servers_rows = conn.execute(
        f"select distinct json_extract(ep.projection_json, '$.mcp_server') as s {join} {where}",
        params,
    ).fetchall()
    servers = sorted(r["s"] for r in servers_rows if r["s"])

    error_calls = conn.execute(
        f"select sum(case when json_extract(ep.projection_json, '$.mcp_is_error') = 1 then 1 else 0 end) {join} {where}",
        params,
    ).fetchone()[0] or 0

    if risk_only:
        risk_calls = total
    else:
        risk_where = where + " and exists (select 1 from risk_signals rs where rs.fact_id = ep.fact_id)"
        risk_calls = conn.execute(f"select count(*) {join} {risk_where}", params).fetchone()[0] or 0

    # 2. 页数据（只加载当前页的 raw_content）
    offset = (page - 1) * page_size
    page_rows = conn.execute(
        f"select ep.fact_id, ep.projection_json, ep.raw_content, of.occurred_at, of.conversation_ref "
        f"{join} {where} order by of.occurred_at desc limit ? offset ?",
        params + [page_size, offset],
    ).fetchall()

    # 3. 风险信号（仅当前页）
    risk_map = _fetch_risk_signals(conn, [r["fact_id"] for r in page_rows])

    items = []
    for row in page_rows:
        try:
            projection = json.loads(row["projection_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(projection, dict):
            continue
        arguments, result_text = _extract_detail(row["raw_content"])
        items.append({
            "fact_id": row["fact_id"],
            "occurred_at": row["occurred_at"],
            "conversation_ref": row["conversation_ref"],
            "mcp_server": projection.get("mcp_server"),
            "mcp_tool": projection.get("mcp_tool"),
            "mcp_duration_ms": projection.get("mcp_duration_ms"),
            "mcp_is_error": projection.get("mcp_is_error", False),
            "mcp_args_summary": projection.get("mcp_args_summary", ""),
            "arguments": arguments,
            "result_text": result_text,
            "risk_signals": risk_map.get(row["fact_id"], []),
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": {
            "servers": servers,
            "total_calls": total,
            "error_calls": error_calls,
            "risk_calls": risk_calls,
        },
    }
