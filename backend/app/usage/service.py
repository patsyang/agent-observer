from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta


ROLLUP_SCOPES = ("total", "session", "conversation", "project", "account", "activity_tag")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def build_usage_rollups(conn: sqlite3.Connection, window: str = "24h") -> dict:
    conn.execute("delete from usage_rollups where window = ?", (window,))
    cutoff = _window_cutoff(window)
    where = "where of.occurred_at >= ?" if cutoff else ""
    params = (cutoff.isoformat(),) if cutoff else ()
    signals = conn.execute(
        f"""
        select us.*, ep.projection_id, of.occurred_at
        from usage_signals us
        join observed_facts of on of.fact_id = us.fact_id
        left join evidence_projections ep on ep.fact_id = us.fact_id
        {where}
        """,
        params,
    ).fetchall()
    grouped: dict[tuple[str, str, str, str], dict] = {}
    for row in signals:
        if not _within_window(row["occurred_at"], window):
            continue
        values = {
            "total": "all",
            "session": row["session_id"],
            "conversation": row["conversation_id"],
            "project": row["project_ref"],
            "account": row["account_ref"],
            "activity_tag": row["activity_tag"],
        }
        for scope in ROLLUP_SCOPES:
            activity_tag = row["activity_tag"] if scope == "activity_tag" else "all"
            key = (scope, values[scope], row["usage_kind"], activity_tag)
            entry = grouped.setdefault(key, {"units": 0, "evidence_refs": []})
            entry["units"] += int(row["units"])
            if row["projection_id"]:
                entry["evidence_refs"].append(row["projection_id"])

    built_at = _now()
    for (scope, scope_value, usage_kind, activity_tag), entry in grouped.items():
        rollup_id = f"{window}:{scope}:{scope_value}:{usage_kind}:{activity_tag}"
        conn.execute(
            """
            insert into usage_rollups (
              rollup_id, window, scope, scope_value, units, usage_kind,
              activity_tag, additive, evidence_refs_json, built_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rollup_id,
                window,
                scope,
                scope_value,
                entry["units"],
                usage_kind,
                activity_tag,
                1 if usage_kind == "attributed" else 0,
                json.dumps(sorted(set(entry["evidence_refs"]))),
                built_at,
            ),
        )
    conn.commit()
    return _read_usage_summary(conn, window=window)


def _empty_summary(window: str) -> dict:
    return {
        "window": window,
        "rollups": [],
        "totals": {
            "associated_units": 0,
            "attributed_units": 0,
            "unknown_units": 0,
        },
    }


def get_usage_summary(conn: sqlite3.Connection, window: str = "24h") -> dict:
    if conn.execute("select count(*) from usage_signals").fetchone()[0] == 0:
        return _empty_summary(window)
    return build_usage_rollups(conn, window=window)


def _read_usage_summary(conn: sqlite3.Connection, window: str = "24h") -> dict:
    rows = conn.execute(
        """
        select * from usage_rollups
        where window = ?
        order by scope, scope_value, usage_kind, activity_tag
        """,
        (window,),
    ).fetchall()
    rollups = [
        {
            "rollup_id": row["rollup_id"],
            "window": row["window"],
            "scope": row["scope"],
            "scope_value": row["scope_value"],
            "units": row["units"],
            "usage_kind": row["usage_kind"],
            "activity_tag": row["activity_tag"],
            "additive": bool(row["additive"]),
            "evidence_refs": json.loads(row["evidence_refs_json"]),
        }
        for row in rows
    ]
    unknown_units = sum(row["units"] for row in rollups if row["activity_tag"] == "unknown")
    return {
        "window": window,
        "rollups": rollups,
        "totals": {
            "associated_units": sum(row["units"] for row in rollups if row["scope"] == "total" and row["usage_kind"] == "associated"),
            "attributed_units": sum(row["units"] for row in rollups if row["scope"] == "total" and row["usage_kind"] == "attributed"),
            "unknown_units": unknown_units,
        },
    }


def _within_window(value: str, window: str) -> bool:
    if window == "all":
        return True
    hours = {"1h": 1, "24h": 24, "7d": 24 * 7}.get(window)
    if hours is None:
        return True
    try:
        occurred = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    return occurred >= datetime.now(UTC) - timedelta(hours=hours)


def _window_cutoff(window: str) -> datetime | None:
    hours = {"1h": 1, "24h": 24, "7d": 24 * 7}.get(window)
    if hours is None:
        return None
    return datetime.now(UTC) - timedelta(hours=hours)
