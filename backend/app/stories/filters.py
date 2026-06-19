from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta


def filter_story_rows(conn: sqlite3.Connection, rows: list[sqlite3.Row], window: str, queue: str) -> list[sqlite3.Row]:
    return [
        row
        for row in rows
        if _story_in_queue(row, queue) and _story_in_window(conn, row, window)
    ]


def _story_in_queue(row: sqlite3.Row, queue: str) -> bool:
    if queue != "actionable":
        return True
    return not str(row["story_key"]).startswith("usage:")


def _story_in_window(conn: sqlite3.Connection, row: sqlite3.Row, window: str) -> bool:
    if window == "all":
        return True
    evidence_refs = json.loads(row["evidence_refs_json"])
    if not evidence_refs:
        return _within_window(row["updated_at"], window)
    placeholders = ",".join("?" for _ in evidence_refs)
    facts = conn.execute(
        f"""
        select of.occurred_at
        from evidence_projections ep
        join observed_facts of on of.fact_id = ep.fact_id
        where ep.projection_id in ({placeholders})
        """,
        evidence_refs,
    ).fetchall()
    if not facts:
        return _within_window(row["updated_at"], window)
    return any(_within_window(fact["occurred_at"], window) for fact in facts)


def _within_window(value: str, window: str) -> bool:
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
