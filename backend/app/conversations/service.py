"""会话查询：只读物化层（conversations / conversation_messages / conversation_hits / FTS）。

写入侧见 ``app.conversations.materialize``（ingest 事务内同步维护）。本模块不再做任何
读时聚合、N+1 关联或运行时 JSON 解析——列表是物化表的索引分页，详情是三条索引扫描，
文本搜索走 FTS5 倒排。

对外三个函数签名不变（routes.py / dev_server_handlers.py 依赖）：
``query_conversations`` / ``get_conversation_query`` / ``get_conversation_for_fact``。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.conversations.time_window import normalize_iso_param, window_cutoff

_PROMPT_CATEGORY = "agent_prompt"
_HIT_COLUMNS = (
    "fact_id, category, fact_type, severity, occurred_at, summary, content_preview, "
    "tool_context_json, sensitive_matches_json, source_line"
)
_MESSAGE_COLUMNS = (
    "fact_id, role, category, occurred_at, content, raw_available, sensitive_matches_json, source_line"
)


# ---------------------------------------------------------------------------
# 列表查询
# ---------------------------------------------------------------------------

def query_conversations(
    conn: sqlite3.Connection,
    *,
    window: str = "1h",
    start_at: str | None = None,
    end_at: str | None = None,
    prompt_query: str | None = None,
    response_query: str | None = None,
    workspace_query: str | None = None,
    agent_type: str | None = None,
    source_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """会话列表（分页 + 时间/agent/source/文本/workspace 过滤），只读 conversations 物化表。"""
    current_page = max(1, int(page or 1))
    limit = max(1, min(int(page_size or 20), 200))
    offset = (current_page - 1) * limit
    prompt = (prompt_query or "").strip()
    response = (response_query or "").strip()
    workspace = (workspace_query or "").strip()
    has_text = bool(prompt or response or workspace)

    where, params = _list_where(window, start_at, end_at, agent_type, source_id)
    qualified = "(prompt_count > 0 and response_count > 0 or model_call_count > 0)"

    if has_text:
        candidate = _text_candidate(conn, prompt=prompt, response=response, workspace=workspace)
        if not candidate:
            return _empty_response(window, start_at, end_at, agent_type, source_id, current_page, limit)
        refs_json = json.dumps(sorted(candidate))
        total = conn.execute(
            f"select count(*) from conversations where {qualified} and {where} "
            f"and conversation_ref in (select value from json_each(?))",
            (*params, refs_json),
        ).fetchone()[0]
        rows = conn.execute(
            f"select * from conversations where {qualified} and {where} "
            f"and conversation_ref in (select value from json_each(?)) "
            f"order by last_event_at desc, conversation_ref limit ? offset ?",
            (*params, refs_json, limit, offset),
        ).fetchall()
    else:
        total = conn.execute(
            f"select count(*) from conversations where {qualified} and {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"select * from conversations where {qualified} and {where} "
            f"order by last_event_at desc, conversation_ref limit ? offset ?",
            (*params, limit, offset),
        ).fetchall()

    return {
        "conversations": [_summary_row(row) for row in rows],
        "total": total,
        "page": current_page,
        "page_size": limit,
        "has_more": offset + len(rows) < total,
        "window": window,
        "start_at": start_at,
        "end_at": end_at,
        "agent_type": agent_type,
        "source_id": source_id,
    }


def _list_where(
    window: str,
    start_at: str | None,
    end_at: str | None,
    agent_type: str | None,
    source_id: str | None,
) -> tuple[str, list]:
    """列表过滤条件。window 下界精确（last_event_at>=cutoff）；start/end 是 overlap 近似。"""
    clauses: list[str] = []
    params: list = []
    normalized_start = normalize_iso_param(start_at)
    normalized_end = normalize_iso_param(end_at)
    if normalized_start and normalized_end:
        clauses.append("last_event_at >= ? and started_at <= ?")
        params.extend([normalized_start, normalized_end])
    elif normalized_start:
        clauses.append("last_event_at >= ?")
        params.append(normalized_start)
    elif normalized_end:
        clauses.append("last_event_at <= ?")
        params.append(normalized_end)
    else:
        cutoff = window_cutoff(window)
        if cutoff:
            clauses.append("last_event_at >= ?")
            params.append(cutoff)
    if agent_type:
        clauses.append("agent_type = ?")
        params.append(agent_type)
    if source_id:
        clauses.append("source_id = ?")
        params.append(source_id)
    return (" and ".join(clauses) if clauses else "1 = 1"), params


def _text_candidate(
    conn: sqlite3.Connection, *, prompt: str, response: str, workspace: str
) -> set[str] | None:
    """文本/workspace 过滤的候选 conversation_ref 集合（prompt AND response AND workspace）。"""
    ref_sets: list[set[str]] = []
    if prompt:
        ref_sets.append(_fts_refs(conn, prompt, "user"))
    if response:
        ref_sets.append(_fts_refs(conn, response, "assistant"))
    candidate: set[str] | None = None
    if ref_sets:
        candidate = set.intersection(*ref_sets)
    if workspace:
        ws_refs = _workspace_refs(conn, workspace)
        candidate = (candidate & ws_refs) if candidate is not None else ws_refs
    return candidate


def _fts_refs(conn: sqlite3.Connection, query: str, role: str) -> set[str]:
    """全文搜索命中的 conversation_ref。trigram 需 ≥3 字符，更短回退 content like。"""
    if len(query) < 3:
        rows = conn.execute(
            "select distinct conversation_ref from conversation_messages "
            "where role = ? and content like ?",
            (role, f"%{query}%"),
        ).fetchall()
    else:
        try:
            rows = conn.execute(
                "select conversation_ref from conversation_messages_fts "
                "where conversation_messages_fts match ? and role = ?",
                (query, role),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "select distinct conversation_ref from conversation_messages "
                "where role = ? and content like ?",
                (role, f"%{query}%"),
            ).fetchall()
    return {row["conversation_ref"] for row in rows}


def _workspace_refs(conn: sqlite3.Connection, workspace: str) -> set[str]:
    rows = conn.execute(
        "select conversation_ref from conversations "
        "where ws_workspace_label like ? or ws_workspace_path like ? or ws_workspace_id like ?",
        (f"%{workspace}%", f"%{workspace}%", f"%{workspace}%"),
    ).fetchall()
    return {row["conversation_ref"] for row in rows}


def _empty_response(
    window: str, start_at: str | None, end_at: str | None,
    agent_type: str | None, source_id: str | None,
    current_page: int, limit: int,
) -> dict:
    return {
        "conversations": [],
        "total": 0,
        "page": current_page,
        "page_size": limit,
        "has_more": False,
        "window": window,
        "start_at": start_at,
        "end_at": end_at,
        "agent_type": agent_type,
        "source_id": source_id,
    }


# ---------------------------------------------------------------------------
# 详情查询
# ---------------------------------------------------------------------------

def get_conversation_query(conn: sqlite3.Connection, conversation_ref: str) -> dict:
    """单个会话详情：conversations 行 + messages + hits（支持 turn|... 截取）。"""
    row = conn.execute(
        "select * from conversations where conversation_ref = ?", (conversation_ref,)
    ).fetchone()
    if row is None:
        raise LookupError(conversation_ref)
    turn = _parse_turn_ref(conversation_ref)
    if turn is None:
        messages = _fetch_all_messages(conn, row["conversation_ref"])
        hits = _fetch_all_hits(conn, row["conversation_ref"])
    else:
        start_line = turn["start_line"]
        message_bucket = _fetch_message_bucket(conn, row["base_ref"], row["source_path_hash"])
        end_line = _next_prompt_line(message_bucket, start_line)
        messages = _slice_rows(message_bucket, start_line, end_line)
        hits = _slice_rows(
            _fetch_hit_bucket(conn, row["base_ref"], row["source_path_hash"]),
            start_line,
            end_line,
        )
    result = {
        **_summary_row(row),
        "messages": [_message_dict(m) for m in messages if m["content"]],
        "hits": [_hit_dict(h) for h in hits],
    }
    # session_title 兜底：物化表里为空时，从 observed_facts 取首条用户提问摘要
    if not result.get("session_title"):
        prompt = conn.execute(
            "select summary from observed_facts where conversation_ref = ? and category = 'agent_prompt' order by occurred_at limit 1",
            (row["conversation_ref"],),
        ).fetchone()
        if prompt and prompt["summary"]:
            result["session_title"] = str(prompt["summary"])[:60]
    return result


def get_conversation_for_fact(conn: sqlite3.Connection, fact_id: str) -> dict:
    """从一个 fact 定位其会话（优先取物化行的 conversation_ref，退化回 observed_facts 算 turn）。"""
    fact = conn.execute(
        "select * from observed_facts where fact_id = ?", (fact_id,)
    ).fetchone()
    if fact is None:
        raise LookupError(fact_id)
    ref = _conversation_ref_for_fact(conn, fact_id) or _fallback_turn_ref(conn, fact)
    return get_conversation_query(conn, ref)


def _conversation_ref_for_fact(conn: sqlite3.Connection, fact_id: str) -> str | None:
    """该 fact 的物化 message/hit 行里写好的 conversation_ref。"""
    row = conn.execute(
        "select conversation_ref from conversation_messages where fact_id = ? "
        "union select conversation_ref from conversation_hits where fact_id = ?",
        (fact_id, fact_id),
    ).fetchone()
    return row["conversation_ref"] if row else None


def _fallback_turn_ref(conn: sqlite3.Connection, fact: sqlite3.Row) -> str:
    """fact 未进物化 messages/hits（如 usage/reasoning）时，回 observed_facts 算 turn 归属。"""
    base_ref = fact["conversation_ref"] or fact["session_ref"] or fact["fact_id"]
    path_hash = fact["source_path_hash"] or ""
    line = _source_line(fact["source_refs_json"])
    if not path_hash or line is None:
        return base_ref
    rows = conn.execute(
        "select source_refs_json, category from observed_facts "
        "where coalesce(nullif(conversation_ref, ''), nullif(session_ref, ''), fact_id) = ? "
        "  and source_path_hash = ? and fact_type != 'collector_health' "
        "order by occurred_at, fact_id",
        (base_ref, path_hash),
    ).fetchall()
    prompt_lines = sorted(
        candidate
        for r in rows
        if r["category"] == _PROMPT_CATEGORY
        and (candidate := _source_line(r["source_refs_json"])) is not None
        and candidate <= line
    )
    return _turn_ref(base_ref, path_hash, prompt_lines[-1]) if prompt_lines else base_ref


def _fetch_all_messages(conn: sqlite3.Connection, conversation_ref: str) -> list[sqlite3.Row]:
    return conn.execute(
        f"select {_MESSAGE_COLUMNS} from conversation_messages "
        "where conversation_ref = ? order by occurred_at, fact_id",
        (conversation_ref,),
    ).fetchall()


def _fetch_message_bucket(
    conn: sqlite3.Connection, base_ref: str, source_path_hash: str
) -> list[sqlite3.Row]:
    return conn.execute(
        f"select {_MESSAGE_COLUMNS} from conversation_messages "
        "where base_ref = ? and source_path_hash = ? order by source_line, occurred_at, fact_id",
        (base_ref, source_path_hash),
    ).fetchall()


def _fetch_all_hits(conn: sqlite3.Connection, conversation_ref: str) -> list[sqlite3.Row]:
    return conn.execute(
        f"select {_HIT_COLUMNS} from conversation_hits "
        "where conversation_ref = ? order by occurred_at, fact_id",
        (conversation_ref,),
    ).fetchall()


def _fetch_hit_bucket(
    conn: sqlite3.Connection, base_ref: str, source_path_hash: str
) -> list[sqlite3.Row]:
    return conn.execute(
        f"select {_HIT_COLUMNS} from conversation_hits "
        "where base_ref = ? and source_path_hash = ? order by occurred_at, fact_id",
        (base_ref, source_path_hash),
    ).fetchall()


def _next_prompt_line(message_bucket: list[sqlite3.Row], start_line: int) -> int | None:
    """桶内下一个 prompt（role=user）的 source_line；无则 None（截到桶尾）。"""
    candidates = sorted(
        item["source_line"]
        for item in message_bucket
        if item["role"] == "user"
        and item["source_line"] is not None
        and item["source_line"] > start_line
    )
    return candidates[0] if candidates else None


def _slice_rows(
    rows: list[sqlite3.Row], start_line: int, end_line: int | None
) -> list[sqlite3.Row]:
    """保留 source_line ∈ [start_line, end_line) 的行（line 为 None 不入选，复刻 _turn_rows）。"""
    return [
        item
        for item in rows
        if item["source_line"] is not None
        and item["source_line"] >= start_line
        and (end_line is None or item["source_line"] < end_line)
    ]


# ---------------------------------------------------------------------------
# 行 → API dict
# ---------------------------------------------------------------------------

def _summary_row(row: sqlite3.Row) -> dict:
    return {
        "conversation_ref": row["conversation_ref"],
        "session_ref": row["session_ref"],
        "session_title": row["session_title"],
        "agent_type": row["agent_type"],
        "source_id": row["source_id"],
        "source_kind": row["source_kind"],
        "workspace": {
            "agent_type": row["ws_agent_type"],
            "workspace_id": row["ws_workspace_id"],
            "workspace_path": row["ws_workspace_path"],
            "workspace_label": row["ws_workspace_label"],
            "workspace_alias_source": row["ws_workspace_alias_source"],
            "workspace_confidence": row["ws_workspace_confidence"],
        },
        "started_at": row["started_at"],
        "last_event_at": row["last_event_at"],
        "prompt_preview": row["prompt_preview"],
        "response_preview": row["response_preview"],
        "event_count": row["event_count"],
        "hit_count": row["hit_count"],
        "token_usage": _usage_dict(row),
    }


def _usage_dict(row: sqlite3.Row) -> dict:
    return {
        "effective_units": row["effective_units"],
        "model_call_count": row["model_call_count"],
        "max_single_call_units": row["max_single_call_units"],
        "cached_input_units": row["cached_input_units"],
        "input_token_units": row["input_token_units"],
        "output_token_units": row["output_token_units"],
        "total_token_units": row["total_token_units"],
        "cache_write_input_units": row["cache_write_input_units"],
        "reasoning_output_units": row["reasoning_output_units"],
        "credit_total": row["credit_total"],
        "cache_observed_input_units": row["cache_observed_input_units"],
        "cache_hit_rate": row["cache_hit_rate"],
    }


def _message_dict(row: sqlite3.Row) -> dict:
    return {
        "fact_id": row["fact_id"],
        "role": row["role"],
        "category": row["category"],
        "occurred_at": row["occurred_at"],
        "content": row["content"],
        "raw_available": bool(row["raw_available"]),
        "sensitive_matches": _loads_list(row["sensitive_matches_json"]),
    }


def _hit_dict(row: sqlite3.Row) -> dict:
    return {
        "fact_id": row["fact_id"],
        "category": row["category"],
        "fact_type": row["fact_type"],
        "severity": row["severity"],
        "occurred_at": row["occurred_at"],
        "summary": row["summary"],
        "content_preview": row["content_preview"],
        "tool_context": _loads_dict(row["tool_context_json"]),
        "sensitive_matches": _loads_list(row["sensitive_matches_json"]),
    }


def _loads_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _loads_dict(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# turn ref 解析（保留：详情 by-fact 定位用）
# ---------------------------------------------------------------------------

def _parse_turn_ref(value: str) -> dict[str, Any] | None:
    parts = value.split("|")
    if len(parts) != 4 or parts[0] != "turn":
        return None
    try:
        start_line = int(parts[3])
    except ValueError:
        return None
    return {"base_ref": parts[1], "source_path_hash": parts[2], "start_line": start_line}


def _turn_ref(base_ref: str, source_path_hash: str, start_line: int) -> str:
    return f"turn|{base_ref}|{source_path_hash}|{start_line}"


def _source_line(source_refs_json: str | None) -> int | None:
    try:
        refs = json.loads(source_refs_json or "{}")
    except json.JSONDecodeError:
        return None
    try:
        return int(refs["line"])
    except (KeyError, TypeError, ValueError):
        return None
