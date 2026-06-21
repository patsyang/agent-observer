from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta


ROLLUP_SCOPES = ("total", "session", "conversation", "project", "account", "activity_tag")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def build_usage_rollups(conn: sqlite3.Connection, window: str = "24h") -> dict:
    conn.execute("delete from usage_rollups where window = ?", (window,))
    rows = _usage_rows(conn, window)
    grouped = _group_usage_rows(rows, window)
    built_at = _now()
    for (scope, scope_value, activity_tag), entry in grouped.items():
        conn.execute(
            """
            insert into usage_rollups (
              rollup_id, window, scope, scope_value, units,
              activity_tag, evidence_refs_json, built_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{window}:{scope}:{scope_value}:{activity_tag}",
                window,
                scope,
                scope_value,
                entry["units"],
                activity_tag,
                json.dumps(sorted(set(entry["evidence_refs"]))),
                built_at,
            ),
        )
    conn.commit()
    return _read_usage_summary(conn, window=window)


def get_usage_summary(conn: sqlite3.Connection, window: str = "24h") -> dict:
    if conn.execute("select count(*) from usage_signals").fetchone()[0] == 0:
        return _empty_summary(window)
    rows = _usage_rows(conn, window)
    grouped = _group_usage_rows(rows, window)
    rollups = [_rollup_payload(window, key, entry) for key, entry in sorted(grouped.items())]
    return _summary_payload(window, rollups, trend=_usage_trend(rows, window), cache_totals=_cache_totals(rows, window))


def _usage_rows(conn: sqlite3.Connection, window: str) -> list[sqlite3.Row]:
    cutoff = _window_cutoff(window)
    where = "where of.occurred_at >= ?" if cutoff else ""
    params = (cutoff.isoformat(),) if cutoff else ()
    return conn.execute(
        f"""
        select us.*, ep.projection_id, ep.projection_json, of.occurred_at
        from usage_signals us
        join observed_facts of on of.fact_id = us.fact_id
        left join evidence_projections ep on ep.fact_id = us.fact_id
        {where}
        """,
        params,
    ).fetchall()


def _empty_summary(window: str) -> dict:
    return {
        "window": window,
        "rollups": [],
        "trend": [],
        "totals": {
            "effective_units": 0,
            "unknown_units": 0,
            "cached_input_units": 0,
            "input_token_units": 0,
            "cache_hit_rate": 0,
        },
    }


def _read_usage_summary(conn: sqlite3.Connection, window: str = "24h") -> dict:
    rows = conn.execute(
        """
        select * from usage_rollups
        where window = ?
        order by scope, scope_value, activity_tag
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
            "activity_tag": row["activity_tag"],
            "evidence_refs": json.loads(row["evidence_refs_json"]),
        }
        for row in rows
    ]
    return _summary_payload(window, rollups)


def _group_usage_rows(rows: list[sqlite3.Row], window: str) -> dict[tuple[str, str, str], dict]:
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
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
            key = (scope, values[scope], activity_tag)
            entry = grouped.setdefault(key, {"units": 0, "evidence_refs": []})
            entry["units"] += int(row["units"])
            if row["projection_id"]:
                entry["evidence_refs"].append(row["projection_id"])
    return grouped


def _rollup_payload(window: str, key: tuple[str, str, str], entry: dict) -> dict:
    scope, scope_value, activity_tag = key
    return {
        "rollup_id": f"{window}:{scope}:{scope_value}:{activity_tag}",
        "window": window,
        "scope": scope,
        "scope_value": scope_value,
        "units": entry["units"],
        "activity_tag": activity_tag,
        "evidence_refs": sorted(set(entry["evidence_refs"])),
    }


def _summary_payload(window: str, rollups: list[dict], trend: list[dict] | None = None, cache_totals: dict | None = None) -> dict:
    unknown_units = sum(row["units"] for row in rollups if row["activity_tag"] == "unknown")
    cache_totals = cache_totals or {"cached_input_units": 0, "input_token_units": 0}
    cached_input_units = int(cache_totals["cached_input_units"])
    input_token_units = int(cache_totals["input_token_units"])
    return {
        "window": window,
        "rollups": rollups,
        "trend": trend or [],
        "totals": {
            "effective_units": sum(row["units"] for row in rollups if row["scope"] == "total"),
            "unknown_units": unknown_units,
            "cached_input_units": cached_input_units,
            "input_token_units": input_token_units,
            "cache_hit_rate": _ratio(cached_input_units, input_token_units),
        },
    }


def _usage_trend(rows: list[sqlite3.Row], window: str) -> list[dict]:
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        if not _within_window(row["occurred_at"], window):
            continue
        bucket = _trend_bucket(row["occurred_at"], window)
        entry = buckets.setdefault(
            bucket,
            {
                "effective_units": 0,
                "unknown_units": 0,
                "cached_input_units": 0,
                "input_token_units": 0,
            },
        )
        units = int(row["units"] or 0)
        entry["effective_units"] += units
        if row["activity_tag"] == "unknown":
            entry["unknown_units"] += units
        cache = _cache_metrics(row)
        entry["cached_input_units"] += cache["cached_input_units"]
        entry["input_token_units"] += cache["input_token_units"]
    return [
        {"bucket": bucket, **values, "cache_hit_rate": _ratio(values["cached_input_units"], values["input_token_units"])}
        for bucket, values in sorted(buckets.items())
    ]


def _cache_totals(rows: list[sqlite3.Row], window: str) -> dict[str, int]:
    totals = {"cached_input_units": 0, "input_token_units": 0}
    for row in rows:
        if not _within_window(row["occurred_at"], window):
            continue
        cache = _cache_metrics(row)
        totals["cached_input_units"] += cache["cached_input_units"]
        totals["input_token_units"] += cache["input_token_units"]
    return totals


def _cache_metrics(row: sqlite3.Row) -> dict[str, int]:
    try:
        projection = json.loads(row["projection_json"] or "{}")
    except (TypeError, ValueError, KeyError):
        projection = {}
    cached = _int(projection.get("cached_input_tokens"))
    input_tokens = _int(projection.get("input_tokens"))
    return {"cached_input_units": cached, "input_token_units": input_tokens}


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0
    return round(numerator / denominator, 4)


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _trend_bucket(value: str, window: str) -> str:
    try:
        occurred = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return str(value)
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    occurred = occurred.astimezone(UTC)
    if window == "1h":
        minute = (occurred.minute // 5) * 5
        return occurred.replace(minute=minute, second=0, microsecond=0).isoformat()
    if window == "24h":
        return occurred.replace(minute=0, second=0, microsecond=0).isoformat()
    return occurred.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


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
