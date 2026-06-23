from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from app.time_ranges import bucket_size_minutes, bucket_start_iso, range_bounds_iso, within_range, window_cutoff


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


def get_usage_summary(
    conn: sqlite3.Connection,
    window: str = "24h",
    agent_type: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict:
    if conn.execute("select count(*) from usage_signals").fetchone()[0] == 0:
        return _empty_summary(window, start_at, end_at)
    rows = _usage_rows(conn, window, agent_type, start_at, end_at)
    grouped = _group_usage_rows(rows, window, start_at, end_at)
    rollups = [_rollup_payload(window, key, entry) for key, entry in sorted(grouped.items())]
    bucket_minutes = bucket_size_minutes(window, start_at, end_at)
    return _summary_payload(
        window,
        rollups,
        trend=_usage_trend(rows, window, bucket_minutes, start_at, end_at),
        metric_totals=_metric_totals(rows, window, start_at, end_at),
        bucket_minutes=bucket_minutes,
    )


def _usage_rows(
    conn: sqlite3.Connection,
    window: str,
    agent_type: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> list[sqlite3.Row]:
    start, end = range_bounds_iso(window, start_at, end_at)
    clauses = []
    params: list[str] = []
    if start:
        clauses.append("of.occurred_at >= ?")
        params.append(start)
    if end:
        clauses.append("of.occurred_at <= ?")
        params.append(end)
    if agent_type:
        clauses.append("of.agent_type = ?")
        params.append(agent_type)
    where = f"where {' and '.join(clauses)}" if clauses else ""
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


def _empty_summary(window: str, start_at: str | None = None, end_at: str | None = None) -> dict:
    return {
        "window": window,
        "bucket_size_minutes": bucket_size_minutes(window, start_at, end_at),
        "rollups": [],
        "trend": [],
        "totals": {
            "effective_units": 0,
            "unknown_units": 0,
            "cached_input_units": 0,
            "input_token_units": 0,
            "output_token_units": 0,
            "total_token_units": 0,
            "cache_write_input_units": 0,
            "reasoning_output_units": 0,
            "credit_total": 0,
            "cache_observed_input_units": 0,
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


def _group_usage_rows(
    rows: list[sqlite3.Row],
    window: str,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict[tuple[str, str, str], dict]:
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        if not within_range(row["occurred_at"], window, start_at, end_at):
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


def _summary_payload(
    window: str,
    rollups: list[dict],
    trend: list[dict] | None = None,
    metric_totals: dict | None = None,
    bucket_minutes: int | None = None,
) -> dict:
    unknown_units = sum(row["units"] for row in rollups if row["activity_tag"] == "unknown")
    metric_totals = metric_totals or _zero_metrics()
    cached_input_units = int(metric_totals["cached_input_units"])
    cache_observed_input_units = int(metric_totals["cache_observed_input_units"])
    return {
        "window": window,
        "bucket_size_minutes": bucket_minutes or bucket_size_minutes(window),
        "rollups": rollups,
        "trend": trend or [],
        "totals": {
            "effective_units": sum(row["units"] for row in rollups if row["scope"] == "total"),
            "unknown_units": unknown_units,
            "input_token_units": int(metric_totals["input_token_units"]),
            "output_token_units": int(metric_totals["output_token_units"]),
            "total_token_units": int(metric_totals["total_token_units"]),
            "cached_input_units": cached_input_units,
            "cache_write_input_units": int(metric_totals["cache_write_input_units"]),
            "reasoning_output_units": int(metric_totals["reasoning_output_units"]),
            "credit_total": round(float(metric_totals["credit_total"]), 4),
            "cache_observed_input_units": cache_observed_input_units,
            "cache_hit_rate": _ratio(cached_input_units, cache_observed_input_units),
        },
    }


def _usage_trend(
    rows: list[sqlite3.Row],
    window: str,
    bucket_minutes: int,
    start_at: str | None = None,
    end_at: str | None = None,
) -> list[dict]:
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        if not within_range(row["occurred_at"], window, start_at, end_at):
            continue
        bucket = bucket_start_iso(row["occurred_at"], bucket_minutes)
        entry = buckets.setdefault(
            bucket,
            {"effective_units": 0, "unknown_units": 0, **_zero_metrics()},
        )
        units = int(row["units"] or 0)
        entry["effective_units"] += units
        if row["activity_tag"] == "unknown":
            entry["unknown_units"] += units
        _add_metrics(entry, _row_metrics(row))
    return [
        {"bucket": bucket, **values, "credit_total": round(float(values["credit_total"]), 4), "cache_hit_rate": _ratio(values["cached_input_units"], values["cache_observed_input_units"])}
        for bucket, values in sorted(buckets.items())
    ]


def _metric_totals(rows: list[sqlite3.Row], window: str, start_at: str | None = None, end_at: str | None = None) -> dict[str, int | float]:
    totals = _zero_metrics()
    for row in rows:
        if not within_range(row["occurred_at"], window, start_at, end_at):
            continue
        _add_metrics(totals, _row_metrics(row))
    return totals


def _zero_metrics() -> dict[str, int | float]:
    return {
        "input_token_units": 0,
        "output_token_units": 0,
        "total_token_units": 0,
        "cached_input_units": 0,
        "cache_write_input_units": 0,
        "reasoning_output_units": 0,
        "credit_total": 0.0,
        "cache_observed_input_units": 0,
    }


def _add_metrics(target: dict[str, int | float], values: dict[str, int | float]) -> None:
    for key, value in values.items():
        target[key] += value


def _row_metrics(row: sqlite3.Row) -> dict[str, int | float]:
    input_tokens = _int(row["input_tokens"])
    cache_observed = bool(row["cache_observed"]) and input_tokens > 0
    return {
        "input_token_units": input_tokens,
        "output_token_units": _int(row["output_tokens"]),
        "total_token_units": _int(row["total_tokens"]),
        "cached_input_units": _int(row["cached_input_tokens"]),
        "cache_write_input_units": _int(row["cache_write_input_tokens"]),
        "reasoning_output_units": _int(row["reasoning_output_tokens"]),
        "credit_total": _float(row["credit"]),
        "cache_observed_input_units": input_tokens if cache_observed else 0,
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


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _window_cutoff(window: str) -> datetime | None:
    return window_cutoff(window)
