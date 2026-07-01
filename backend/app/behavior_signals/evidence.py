from __future__ import annotations

import sqlite3

from app.behavior_signals.common import loads
from app.evidence.presentation import projection_preview, raw_available, raw_status_label, source_event_type, source_label


def evidence_entries(conn: sqlite3.Connection, fact: sqlite3.Row) -> list[dict]:
    projections = conn.execute(
        "select * from evidence_projections where fact_id = ? order by projection_id",
        (fact["fact_id"],),
    ).fetchall()
    refs = loads(fact["source_refs_json"])
    specific = loads(fact["source_specific_json"])
    if not projections:
        return [_entry_base(fact, refs, specific, fact["fact_id"], fact["category"], fact["summary"])]
    entries = []
    for projection in projections:
        projection_json = loads(projection["projection_json"])
        preview = projection_preview(projection_json, projection["raw_content"], fact["summary"], projection["category"])
        entry = _entry_base(fact, refs, specific, projection["projection_id"], projection["category"], preview)
        entry["raw_available"] = raw_available(bool(projection["upload_raw"]), projection["raw_content"])
        entry["raw_status"] = raw_status_label(bool(projection["upload_raw"]), projection["raw_content"])
        entry["projection"] = projection_json
        entries.append(entry)
    return entries


def enrichment_entries(conn: sqlite3.Connection, signal_id: str) -> list[dict]:
    rows = conn.execute(
        """
        select result_id, status, summary, output_schema, projection_json, created_at
        from enrichment_results
        where signal_id = ?
        order by created_at
        """,
        (signal_id,),
    ).fetchall()
    return [
        {
            "evidence_ref": row["result_id"],
            "fact_id": None,
            "category": "enrichment_result",
            "summary": row["summary"],
            "quality": "high" if row["status"] == "succeeded" else "low",
            "occurred_at": row["created_at"],
            "fact_type": "enrichment",
            "source_event_type": "enrichment_result",
            "source_label": "工具失败上下文补证" if row["output_schema"] == "tool_failure_context.v1" else "本机补证结果",
            "content_preview": _enrichment_preview(row["summary"], loads(row["projection_json"])),
            "raw_available": False,
            "raw_status": "补证摘要",
        }
        for row in rows
    ]


def enrichment_status_summary(conn: sqlite3.Connection, signal_id: str) -> dict:
    row = conn.execute(
        "select status, reason_code from enrichment_jobs where signal_id = ? order by rowid desc limit 1",
        (signal_id,),
    ).fetchone()
    if row is None:
        return {"status": "none", "reason_code": None}
    return {"status": row["status"], "reason_code": row["reason_code"]}


def usage_summary(conn: sqlite3.Connection, fact_ids: list[str]) -> dict:
    if not fact_ids:
        return {"effective_units": 0, "cached_units": 0, "cache_hit_rate": None, "no_usage_reason": "没有用量证据"}
    placeholders = ",".join("?" for _ in fact_ids)
    rows = conn.execute(
        f"""
        select units, activity_tag, cached_input_tokens, input_tokens, cache_observed
        from usage_signals
        where fact_id in ({placeholders})
        """,
        fact_ids,
    ).fetchall()
    effective = sum(int(row["units"] or 0) for row in rows)
    cached = sum(int(row["cached_input_tokens"] or 0) for row in rows)
    observed_input = sum(int(row["input_tokens"] or 0) for row in rows if bool(row["cache_observed"]))
    return {
        "effective_units": effective,
        "cached_units": cached,
        "cache_hit_rate": round(cached / observed_input, 4) if observed_input > 0 else None,
        "no_usage_reason": None if rows else "没有用量证据",
    }


def usage_facts_for_signals(conn: sqlite3.Connection, fact_ids: list[str]) -> list[dict]:
    """Return usage fact rows joined to observed_facts for a list of fact IDs.

    Used by usage anomaly builders to attach usage evidence to signals.
    """
    if not fact_ids:
        return []
    placeholders = ",".join("?" for _ in fact_ids)
    rows = conn.execute(
        f"""
        select us.*, of.occurred_at, of.conversation_ref, of.session_ref, of.agent_type
        from usage_signals us
        join observed_facts of on of.fact_id = us.fact_id
        where us.fact_id in ({placeholders})
        order by us.fact_id
        """,
        fact_ids,
    ).fetchall()
    return [dict(row) for row in rows]


def _entry_base(fact: sqlite3.Row, refs: dict, specific: dict, evidence_ref: str, category: str, preview: str) -> dict:
    return {
        "evidence_ref": evidence_ref,
        "fact_id": fact["fact_id"],
        "category": category,
        "summary": fact["summary"],
        "quality": fact["quality"],
        "occurred_at": fact["occurred_at"],
        "fact_type": fact["fact_type"],
        "conversation_ref": fact["conversation_ref"] or refs.get("conversation_ref") or "",
        "source_event_type": source_event_type(specific),
        "source_label": source_label(refs),
        "content_preview": preview,
        "raw_available": False,
        "raw_status": "无证据投影",
    }


def _enrichment_preview(summary: str, projection: dict) -> str:
    failures = projection.get("matched_failures")
    conversations = projection.get("matched_conversations")
    if isinstance(failures, list) and failures:
        count = len(conversations) if isinstance(conversations, list) else 0
        return f"{summary} 命中 {len(failures)} 条失败工具调用，关联 {count} 个会话。"
    return summary
