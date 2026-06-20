from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.collectors.service import list_collectors
from app.facts.service import query_facts
from app.stories.service import list_stories


def get_dashboard_summary(conn: sqlite3.Connection, window: str = "1h") -> dict:
    collectors = list_collectors(conn)
    stories = list_stories(conn, window=window, queue="actionable", page=1, page_size=5)
    facts = query_facts(conn, window=window, include_health=False, page=1, page_size=5, time_basis="occurred")
    risks = _risk_top(conn, window)
    return {
        "window": window,
        "collectors": {
            "total": len(collectors),
            "online": sum(1 for collector in collectors if collector["source_status"] == "online"),
            "degraded": sum(1 for collector in collectors if collector["source_status"] == "degraded"),
            "offline": sum(1 for collector in collectors if collector["source_status"] == "offline"),
            "items": collectors[:5],
        },
        "stories": {
            "total": stories["total"],
            "items": stories["stories"],
        },
        "facts": {
            "total": facts["total"],
            "items": facts["facts"],
            "time_basis": "occurred",
        },
        "risks": {
            "top": risks[:5],
            "total": len(risks),
        },
    }


def _risk_top(conn: sqlite3.Connection, window: str) -> list[dict]:
    clauses = []
    params: list[str] = []
    cutoff = _window_cutoff(window)
    if cutoff:
        clauses.append("of.occurred_at >= ?")
        params.append(cutoff)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    return [
        {
            "risk_type": row["risk_type"],
            "object_type": row["object_type"],
            "count": row["count"],
            "highest_severity": row["highest_severity"],
            "last_seen_at": row["last_seen_at"],
            "top_examples": [row["top_example"]] if row["top_example"] else [],
        }
        for row in conn.execute(
            f"""
            select rs.risk_type,
                   rs.object_type,
                   count(*) as count,
                   max(rs.severity) as highest_severity,
                   max(of.occurred_at) as last_seen_at,
                   max(of.summary) as top_example
            from risk_signals rs
            join observed_facts of on of.fact_id = rs.fact_id
            {where}
            group by rs.risk_type, rs.object_type
            order by count desc, last_seen_at desc
            limit 10
            """,
            params,
        ).fetchall()
    ]


def _window_cutoff(window: str) -> str | None:
    if window == "all":
        return None
    hours = {"1h": 1, "24h": 24, "7d": 24 * 7}.get(window)
    if hours is None:
        return None
    return (datetime.now(UTC) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
