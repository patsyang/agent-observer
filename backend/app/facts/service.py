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
        "ingested_at": row["created_at"],
        "source": row["source"],
        "promoted_to_story": bool(row["promoted_to_story"]),
    }
    source_refs = _loads(row["source_refs_json"])
    source_specific = _loads(row["source_specific_json"])
    fact["source_event_type"] = source_event_type(source_specific)
    fact["source_label"] = source_label(source_refs)
    if not conn:
        fact["content_preview"] = row["content_preview"] or row["summary"]
        fact["raw_available"] = bool(row["raw_available"])
        fact["raw_status"] = row["raw_status"] or "未上传原文，可查看结构化摘要"
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
    page: int | None = None,
    page_size: int | None = None,
    time_basis: str = "occurred",
) -> dict:
    page_limit = max(1, min(int(page_size or limit or 50), 200))
    if page is not None:
        current_page = max(1, int(page))
        page_offset = (current_page - 1) * page_limit
    else:
        page_offset = max(0, int(offset or 0))
        current_page = page_offset // page_limit + 1
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
    cutoff = _window_cutoff(window)
    time_column = "created_at" if time_basis == "ingested" else "occurred_at"
    if cutoff:
        clauses.append(f"{time_column} >= ?")
        params.append(cutoff)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    total = conn.execute(f"select count(*) as total from observed_facts {where}", params).fetchone()["total"]
    rows = conn.execute(
        f"""
        select * from observed_facts
        {where}
        order by {time_column} desc, occurred_at desc, fact_id
        limit ? offset ?
        """,
        [*params, page_limit, page_offset],
    ).fetchall()
    return {
        "facts": [_fact(row) for row in rows],
        "total": int(total),
        "limit": page_limit,
        "offset": page_offset,
        "page": current_page,
        "page_size": page_limit,
        "has_more": page_offset + len(rows) < int(total),
        "time_basis": time_basis if time_basis in {"occurred", "ingested"} else "occurred",
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
        "sensitive_matches": _sensitive_matches(projection_payloads),
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


def _sensitive_matches(projections: list[dict]) -> list[dict]:
    matches: list[dict] = []
    for projection in projections:
        value = projection["projection_json"].get("sensitive_matches")
        if isinstance(value, list):
            matches.extend(match for match in value if isinstance(match, dict) and match.get("confidence") == "high")
    return matches


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


def _window_cutoff(window: str) -> str | None:
    if window == "all":
        return None
    hours = {"1h": 1, "24h": 24, "7d": 24 * 7}.get(window)
    if hours is None:
        return None
    return (datetime.now(UTC) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
