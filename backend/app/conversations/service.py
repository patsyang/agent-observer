from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.conversations.filters import filter_conversations
from app.conversations.time_window import normalize_iso_param, window_cutoff
from app.conversations.workspace import workspace_from_rows
from app.evidence.presentation import projection_preview

def query_conversations(
    conn: sqlite3.Connection,
    *,
    window: str = "1h",
    start_at: str | None = None,
    end_at: str | None = None,
    prompt_query: str | None = None,
    response_query: str | None = None,
    workspace_query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    rows = _conversation_rows(conn, window=window, start_at=start_at, end_at=end_at)
    conversations = [_summary(conn, ref, facts) for ref, facts in _group_by_conversation(rows).items()]
    conversations = [item for item in conversations if _has_input_or_output(item)]
    conversations = filter_conversations(
        conversations,
        prompt_query=prompt_query,
        response_query=response_query,
        workspace_query=workspace_query,
    )
    conversations.sort(key=lambda item: (item["last_event_at"] or "", item["conversation_ref"]), reverse=True)
    current_page = max(1, int(page or 1))
    limit = max(1, min(int(page_size or 50), 200))
    offset = (current_page - 1) * limit
    page_items = [_public_summary(item) for item in conversations[offset : offset + limit]]
    return {
        "conversations": page_items,
        "total": len(conversations),
        "page": current_page,
        "page_size": limit,
        "has_more": offset + len(page_items) < len(conversations),
        "window": window,
        "start_at": start_at,
        "end_at": end_at,
    }

def get_conversation_query(conn: sqlite3.Connection, conversation_ref: str) -> dict:
    rows = _detail_rows(conn, conversation_ref)
    if not rows:
        raise LookupError(conversation_ref)
    summary = _public_summary(_summary(conn, conversation_ref, rows))
    return {
        **summary,
        "messages": [message for row in rows if (message := _message(row)) and message["content"]],
        "hits": [_hit(row) for row in rows if row["fact_type"] in {"error", "risk", "tool", "unknown"}],
    }

def _detail_rows(conn: sqlite3.Connection, conversation_ref: str) -> list[sqlite3.Row]:
    turn = _parse_turn_ref(conversation_ref)
    if turn is not None:
        return _turn_detail_rows(conn, turn)
    return conn.execute(
        """
        select f.*, p.projection_id, p.category as projection_category,
               p.projection_json, p.upload_raw, p.raw_content
        from observed_facts f
        left join evidence_projections p on p.projection_id = (
          select projection_id from evidence_projections
          where fact_id = f.fact_id
          order by projection_id
          limit 1
        )
        where coalesce(nullif(f.conversation_ref, ''), nullif(f.session_ref, ''), f.fact_id) = ?
          and f.fact_type not in ('collector_health', 'usage')
        order by f.occurred_at, f.fact_id
        """,
        (conversation_ref,),
    ).fetchall()

def _turn_detail_rows(conn: sqlite3.Connection, turn: dict[str, object]) -> list[sqlite3.Row]:
    base_ref = str(turn["base_ref"])
    path_hash = str(turn["source_path_hash"])
    start_line = int(turn["start_line"])
    rows = conn.execute(
        """
        select f.*, p.projection_id, p.category as projection_category,
               p.projection_json, p.upload_raw, p.raw_content
        from observed_facts f
        left join evidence_projections p on p.projection_id = (
          select projection_id from evidence_projections
          where fact_id = f.fact_id
          order by projection_id
          limit 1
        )
        where coalesce(nullif(f.conversation_ref, ''), nullif(f.session_ref, ''), f.fact_id) = ?
          and f.source_path_hash = ?
          and f.fact_type != 'collector_health'
        order by f.occurred_at, f.fact_id
        """,
        (base_ref, path_hash),
    ).fetchall()
    end_line = _next_prompt_line(rows, start_line)
    return [
        row
        for row in rows
        if (line := _source_line(row)) is not None and line >= start_line and (end_line is None or line < end_line)
    ]

def get_conversation_for_fact(conn: sqlite3.Connection, fact_id: str) -> dict:
    row = conn.execute(
        """
        select *
        from observed_facts
        where fact_id = ?
        """,
        (fact_id,),
    ).fetchone()
    if row is None:
        raise LookupError(fact_id)
    return get_conversation_query(conn, _turn_ref_for_fact(conn, row))

def _conversation_rows(
    conn: sqlite3.Connection,
    *,
    window: str,
    start_at: str | None,
    end_at: str | None,
) -> list[sqlite3.Row]:
    clauses = ["f.fact_type != 'collector_health'"]
    params: list[str] = []
    normalized_start = normalize_iso_param(start_at)
    normalized_end = normalize_iso_param(end_at)
    if normalized_start:
        clauses.append("datetime(f.occurred_at) >= datetime(?)")
        params.append(normalized_start)
    if normalized_end:
        clauses.append("datetime(f.occurred_at) <= datetime(?)")
        params.append(normalized_end)
    if not normalized_start and not normalized_end:
        cutoff = window_cutoff(window)
        if cutoff:
            clauses.append("datetime(f.occurred_at) >= datetime(?)")
            params.append(cutoff)
    where = " and ".join(clauses)
    return conn.execute(
        f"""
        select f.*, p.projection_id, p.category as projection_category,
               p.projection_json, p.upload_raw, p.raw_content
        from observed_facts f
        left join evidence_projections p on p.projection_id = (
          select projection_id from evidence_projections
          where fact_id = f.fact_id
          order by projection_id
          limit 1
        )
        where {where}
        order by f.occurred_at desc, f.fact_id
        """,
        params,
    ).fetchall()

def _group_by_conversation(rows: list[sqlite3.Row]) -> dict[str, list[sqlite3.Row]]:
    grouped: dict[str, list[sqlite3.Row]] = {}
    buckets: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        base_ref = row["conversation_ref"] or row["session_ref"] or row["fact_id"]
        path_hash = row["source_path_hash"] or ""
        buckets.setdefault((base_ref, path_hash), []).append(row)
    for (base_ref, path_hash), bucket in buckets.items():
        if not path_hash or not any(row["category"] == "codex_prompt" and _source_line(row) is not None for row in bucket):
            grouped.setdefault(base_ref, []).extend(bucket)
            continue
        current_ref: str | None = None
        for row in sorted(bucket, key=_source_order):
            line = _source_line(row)
            if row["category"] == "codex_prompt" and line is not None:
                current_ref = _turn_ref(base_ref, path_hash, line)
            ref = current_ref or base_ref
            grouped.setdefault(ref, []).append(row)
    return grouped

def _summary(conn: sqlite3.Connection, conversation_ref: str, rows: list[sqlite3.Row]) -> dict:
    ordered = sorted(rows, key=lambda row: (row["occurred_at"], row["fact_id"]))
    prompt = _first_text(ordered, {"codex_prompt"}, {"user"})
    response = _first_text(ordered, {"codex_message"}, {"assistant"})
    prompt_search = _all_text(ordered, {"codex_prompt"}, {"user"})
    response_search = _all_text(ordered, {"codex_message"}, {"assistant"})
    return {
        "conversation_ref": conversation_ref,
        "session_ref": _first_value(ordered, "session_ref"),
        "session_title": _session_title(ordered),
        "workspace": workspace_from_rows(ordered),
        "started_at": ordered[0]["occurred_at"],
        "last_event_at": ordered[-1]["occurred_at"],
        "prompt_preview": _truncate(prompt),
        "response_preview": _truncate(response),
        "_prompt_search_text": prompt_search,
        "_response_search_text": response_search,
        "event_count": len(ordered),
        "hit_count": sum(1 for row in ordered if row["fact_type"] in {"error", "risk", "tool", "unknown"}),
        "token_usage": _usage(conn, conversation_ref, ordered),
    }

def _has_input_or_output(item: dict) -> bool:
    has_prompt = bool(item["prompt_preview"] or item.get("_prompt_search_text"))
    has_response = bool(item["response_preview"] or item.get("_response_search_text"))
    return has_prompt and has_response

def _public_summary(item: dict) -> dict:
    return {key: value for key, value in item.items() if not key.startswith("_")}

def _first_text(rows: list[sqlite3.Row], categories: set[str], roles: set[str]) -> str:
    for row in rows:
        projection = _projection(row)
        role = str(projection.get("role") or "")
        if row["category"] in categories or role in roles:
            text = _projection_text(row, projection)
            if text:
                return text
    return ""

def _all_text(rows: list[sqlite3.Row], categories: set[str], roles: set[str]) -> str:
    values = []
    for row in rows:
        projection = _projection(row)
        role = str(projection.get("role") or "")
        if row["category"] in categories or role in roles:
            text = _projection_text(row, projection)
            if text:
                values.append(text)
    return "\n".join(values)

def _message(row: sqlite3.Row) -> dict:
    projection = _projection(row)
    role = str(projection.get("role") or "")
    if row["category"] == "codex_prompt":
        role = "user"
    elif row["category"] == "codex_message":
        role = "assistant"
    elif role not in {"user", "assistant"}:
        return {}
    content = _projection_text(row, projection)
    return {
        "fact_id": row["fact_id"],
        "role": role,
        "category": row["category"],
        "occurred_at": row["occurred_at"],
        "content": content or row["content_preview"] or row["summary"],
        "raw_available": bool(row["raw_available"]),
    }


def _hit(row: sqlite3.Row) -> dict:
    projection = _projection(row)
    return {
        "fact_id": row["fact_id"],
        "category": row["category"],
        "fact_type": row["fact_type"],
        "severity": row["severity"],
        "occurred_at": row["occurred_at"],
        "summary": row["summary"],
        "content_preview": row["content_preview"]
        or projection_preview(projection, row["raw_content"], row["summary"], row["projection_category"] or row["category"]),
        "tool_context": _tool_context(projection),
    }


def _tool_context(projection: dict) -> dict | None:
    if not any(projection.get(key) not in (None, "") for key in ("command", "command_excerpt", "tool_name", "exit_code", "is_timeout")):
        return None
    return {
        "tool_name": str(projection.get("tool_name") or projection.get("tool") or projection.get("name") or ""),
        "command": str(projection.get("command") or ""),
        "command_excerpt": str(projection.get("command_excerpt") or projection.get("command") or ""),
        "command_category": str(projection.get("command_category") or ""),
        "exit_code": projection.get("exit_code"),
        "is_timeout": bool(projection.get("is_timeout")),
        "timeout_ms": projection.get("timeout_ms"),
        "timeout_after_ms": projection.get("timeout_after_ms"),
        "wall_time_seconds": projection.get("wall_time_seconds"),
        "error_excerpt": str(projection.get("error_excerpt") or ""),
        "call_id": str(projection.get("call_id") or ""),
    }


def _usage(conn: sqlite3.Connection, conversation_ref: str, rows: list[sqlite3.Row] | None = None) -> dict:
    if rows is not None:
        fact_ids = [row["fact_id"] for row in rows if row["fact_type"] == "usage"]
        if fact_ids:
            placeholders = ",".join("?" for _ in fact_ids)
            usage_samples = conn.execute(
                f"""
                select us.units, p.projection_json
                from usage_signals us
                left join evidence_projections p on p.fact_id = us.fact_id
                where us.fact_id in ({placeholders})
                """,
                fact_ids,
            ).fetchall()
            return _usage_payload(usage_samples)
    rows = conn.execute(
        """
        select us.units, p.projection_json
        from usage_signals us
        join observed_facts f on f.fact_id = us.fact_id
        left join evidence_projections p on p.fact_id = us.fact_id
        where us.conversation_id = ? or f.conversation_ref = ?
        """,
        (conversation_ref, conversation_ref),
    ).fetchall()
    return _usage_payload(rows)


def _usage_payload(rows: list[sqlite3.Row]) -> dict:
    sample_units = [int(row["units"] or 0) for row in rows]
    cached_input_units = 0
    input_token_units = 0
    for row in rows:
        cache = _cache_metrics(row)
        cached_input_units += cache["cached_input_units"]
        input_token_units += cache["input_token_units"]
    effective = sum(sample_units)
    return {
        "effective_units": effective,
        "model_call_count": len(sample_units),
        "max_single_call_units": max(sample_units, default=0),
        "cached_input_units": cached_input_units,
        "input_token_units": input_token_units,
        "cache_hit_rate": _ratio(cached_input_units, input_token_units),
    }


def _cache_metrics(row: sqlite3.Row) -> dict[str, int]:
    try:
        projection = json.loads(row["projection_json"] or "{}")
    except (TypeError, ValueError, KeyError):
        projection = {}
    return {
        "cached_input_units": _int(projection.get("cached_input_tokens")),
        "input_token_units": _int(projection.get("input_tokens")),
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0
    return round(numerator / denominator, 4)


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _turn_ref_for_fact(conn: sqlite3.Connection, fact: sqlite3.Row) -> str:
    base_ref = fact["conversation_ref"] or fact["session_ref"] or fact["fact_id"]
    path_hash = fact["source_path_hash"] or ""
    line = _source_line(fact)
    if not path_hash or line is None:
        return base_ref
    rows = conn.execute(
        """
        select *
        from observed_facts
        where coalesce(nullif(conversation_ref, ''), nullif(session_ref, ''), fact_id) = ?
          and source_path_hash = ?
          and fact_type != 'collector_health'
        order by occurred_at, fact_id
        """,
        (base_ref, path_hash),
    ).fetchall()
    prompt_lines = sorted(
        candidate
        for row in rows
        if row["category"] == "codex_prompt" and (candidate := _source_line(row)) is not None and candidate <= line
    )
    return _turn_ref(base_ref, path_hash, prompt_lines[-1]) if prompt_lines else base_ref


def _next_prompt_line(rows: list[sqlite3.Row], start_line: int) -> int | None:
    prompt_lines = sorted(
        line
        for row in rows
        if row["category"] == "codex_prompt" and (line := _source_line(row)) is not None and line > start_line
    )
    return prompt_lines[0] if prompt_lines else None


def _source_order(row: sqlite3.Row) -> tuple[int, str, str]:
    line = _source_line(row)
    return (line if line is not None else 10**12, row["occurred_at"], row["fact_id"])


def _source_line(row: sqlite3.Row) -> int | None:
    try:
        refs = json.loads(row["source_refs_json"] or "{}")
    except json.JSONDecodeError:
        return None
    try:
        return int(refs["line"])
    except (KeyError, TypeError, ValueError):
        return None


def _turn_ref(base_ref: str, source_path_hash: str, start_line: int) -> str:
    return f"turn|{base_ref}|{source_path_hash}|{start_line}"


def _parse_turn_ref(value: str) -> dict[str, object] | None:
    parts = value.split("|")
    if len(parts) != 4 or parts[0] != "turn":
        return None
    try:
        start_line = int(parts[3])
    except ValueError:
        return None
    return {"base_ref": parts[1], "source_path_hash": parts[2], "start_line": start_line}


def _projection(row: sqlite3.Row) -> dict[str, Any]:
    try:
        parsed = json.loads(row["projection_json"] or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _projection_text(row: sqlite3.Row, projection: dict[str, Any]) -> str:
    for key in ("prompt_text", "content_text", "message_text", "reasoning_text"):
        value = projection.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw_text = _raw_text(row["raw_content"])
    if raw_text.strip():
        return raw_text.strip()
    role = str(projection.get("role") or "")
    label = ""
    if row["category"] == "codex_prompt" or role == "user":
        label = "提交 Prompt"
    elif row["category"] == "codex_message" or role == "assistant":
        label = "响应内容"
    if not label:
        return ""
    try:
        length = int(projection.get("content_length") or 0)
    except (TypeError, ValueError):
        length = 0
    return f"{label} 原文未上传" + (f"，长度 {length} 字符" if length > 0 else "")


def _raw_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return _extract_text(parsed)


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(part for item in value if (part := _extract_text(item)))
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "message", "prompt", "output", "result"):
        if key in value:
            text = _extract_text(value[key])
            if text:
                return text
    if "payload" in value:
        return _extract_text(value["payload"])
    return ""


def _first_value(rows: list[sqlite3.Row], key: str) -> str:
    for row in rows:
        if row[key]:
            return str(row[key])
    return ""


def _session_title(rows: list[sqlite3.Row]) -> str:
    for row in rows:
        try:
            refs = json.loads(row["source_refs_json"] or "{}")
        except json.JSONDecodeError:
            continue
        title = str(refs.get("session_title") or "").strip()
        if title:
            return title
    return ""


def _truncate(value: str, limit: int = 220) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}..."
