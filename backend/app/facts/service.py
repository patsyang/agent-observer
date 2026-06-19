from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from app.evidence.presentation import projection_preview, raw_available, raw_status_label, source_event_type, source_label


def _loads(value: str) -> dict:
    return json.loads(value or "{}")


def _fact(row: sqlite3.Row, conn: sqlite3.Connection | None = None) -> dict:
    fact = {
        "fact_id": row["fact_id"],
        "source_event_id": row["source_event_id"],
        "fact_type": row["fact_type"],
        "category": row["category"],
        "quality": row["quality"],
        "severity": row["severity"],
        "summary": row["summary"],
        "occurred_at": row["occurred_at"],
        "source": row["source"],
        "promoted_to_story": bool(row["promoted_to_story"]),
    }
    source_refs = _loads(row["source_refs_json"])
    source_specific = _loads(row["source_specific_json"])
    fact["source_event_type"] = source_event_type(source_specific)
    fact["source_label"] = source_label(source_refs)
    if conn is None:
        return fact
    projection = _first_projection(conn, row["fact_id"])
    if projection is None:
        fact["content_preview"] = row["summary"]
        fact["raw_available"] = False
        fact["raw_status"] = "无证据投影"
        return fact
    projection_json = _loads(projection["projection_json"])
    fact["content_preview"] = projection_preview(
        projection_json,
        projection["raw_content"],
        row["summary"],
        projection["category"],
    )
    fact["raw_available"] = raw_available(bool(projection["upload_raw"]), projection["raw_content"])
    fact["raw_status"] = raw_status_label(bool(projection["upload_raw"]), projection["raw_content"])
    return fact


def query_facts(
    conn: sqlite3.Connection,
    *,
    quality: str | None = None,
    fact_type: str | None = None,
    source: str | None = None,
    window: str = "all",
    include_health: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    page_limit = max(1, min(int(limit or 50), 200))
    page_offset = max(0, int(offset or 0))
    clauses: list[str] = []
    params: list[str] = []
    if quality:
        clauses.append("quality = ?")
        params.append(quality)
    if fact_type:
        clauses.append("fact_type = ?")
        params.append(fact_type)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if not include_health:
        clauses.append("fact_type != ?")
        params.append("collector_health")
    where = f"where {' and '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        select * from observed_facts
        {where}
        order by occurred_at desc, fact_id
        """,
        params,
    ).fetchall()
    filtered = [row for row in rows if _within_window(row["occurred_at"], window)]
    page = filtered[page_offset : page_offset + page_limit]
    return {
        "facts": [_fact(row, conn) for row in page],
        "total": len(filtered),
        "limit": page_limit,
        "offset": page_offset,
    }


def get_fact_detail(conn: sqlite3.Connection, fact_id: str) -> dict:
    fact_row = conn.execute("select * from observed_facts where fact_id = ?", (fact_id,)).fetchone()
    if fact_row is None:
        raise LookupError(fact_id)
    projections = conn.execute(
        "select * from evidence_projections where fact_id = ? order by projection_id", (fact_id,)
    ).fetchall()
    if not projections:
        raise LookupError(f"{fact_id}:projection")
    projection_payloads = [_projection(row) for row in projections]
    return {
        "fact": _fact(fact_row, conn),
        "evidence_projection": projection_payloads[0],
        "evidence_projections": projection_payloads,
        "source_refs": json.loads(fact_row["source_refs_json"]),
        "source_specific_json": json.loads(fact_row["source_specific_json"]),
    }


def _projection(row: sqlite3.Row) -> dict:
    return {
        "projection_id": row["projection_id"],
        "fact_id": row["fact_id"],
        "category": row["category"],
        "span": row["span"],
        "raw_hash": row["raw_hash"],
        "projection_json": json.loads(row["projection_json"]),
        "upload_raw": bool(row["upload_raw"]),
        "raw_content": row["raw_content"],
    }


def _first_projection(conn: sqlite3.Connection, fact_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "select * from evidence_projections where fact_id = ? order by projection_id limit 1",
        (fact_id,),
    ).fetchone()


def _within_window(value: str, window: str) -> bool:
    if window == "all":
        return True
    hours = {"1h": 1, "24h": 24, "7d": 24 * 7}.get(window)
    if hours is None:
        return True
    try:
        occurred = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    return occurred.astimezone(UTC) >= cutoff
