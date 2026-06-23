from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.collectors.service import list_collectors
from app.facts.service import query_facts
from app.behavior_signals.service import list_signals
from app.time_ranges import range_bounds_iso, window_cutoff_iso


def get_dashboard_summary(
    conn: sqlite3.Connection,
    window: str = "1h",
    agent_type: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict:
    collectors = _filter_collectors(list_collectors(conn), agent_type)
    signals = list_signals(conn, window=window, agent_type=agent_type, start_at=start_at, end_at=end_at, page=1, page_size=5)
    facts = query_facts(
        conn,
        window=window,
        agent_type=agent_type,
        include_health=False,
        page=1,
        page_size=5,
        time_basis="occurred",
        start_at=start_at,
        end_at=end_at,
    )
    risks = _risk_top(conn, window, agent_type, start_at, end_at)
    return {
        "window": window,
        "collectors": {
            "total": len(collectors),
            "online": sum(1 for collector in collectors if collector["source_status"] == "online"),
            "degraded": sum(1 for collector in collectors if collector["source_status"] == "degraded"),
            "offline": sum(1 for collector in collectors if collector["source_status"] == "offline"),
            "items": collectors[:5],
        },
        "signals": {
            "total": signals["total"],
            "items": signals["signals"],
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


def _filter_collectors(collectors: list[dict], agent_type: str | None) -> list[dict]:
    if not agent_type:
        return collectors
    return [
        collector
        for collector in collectors
        if any(source.get("agent_type") == agent_type for source in collector.get("sources", []))
    ]


def _risk_top(
    conn: sqlite3.Connection,
    window: str,
    agent_type: str | None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> list[dict]:
    clauses = []
    params: list[str] = []
    cutoff, range_end = range_bounds_iso(window, start_at, end_at)
    if cutoff:
        clauses.append("of.occurred_at >= ?")
        params.append(cutoff)
    if range_end:
        clauses.append("of.occurred_at <= ?")
        params.append(range_end)
    if agent_type:
        clauses.append("of.agent_type = ?")
        params.append(agent_type)
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
    return window_cutoff_iso(window)


def _local_today_start() -> datetime:
    local_now = datetime.now().astimezone()
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _local_week_start() -> datetime:
    today = _local_today_start()
    return today - timedelta(days=today.astimezone().weekday())
