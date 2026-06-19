from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from app.sensitivity import sensitive_categories_from_text


def get_risk_summary(conn: sqlite3.Connection, *, mode: str = "summary", window: str = "24h") -> dict:
    cutoff = _window_cutoff(window)
    rows = conn.execute(
        """
        select rs.signal_id, rs.fact_id, rs.risk_type, rs.severity, rs.object_type,
               of.summary,
               ep.projection_id, ep.projection_json, ep.raw_content, of.occurred_at
        from risk_signals rs
        join observed_facts of on of.fact_id = rs.fact_id
        left join evidence_projections ep on ep.fact_id = rs.fact_id
        order by of.occurred_at desc
        """
    ).fetchall()
    signals: dict[str, dict] = {}
    for row in rows:
        if cutoff and _parse_time(row["occurred_at"]) < cutoff:
            continue
        signal = signals.setdefault(
            row["signal_id"],
            {
                "risk_type": row["risk_type"],
                "object_type": row["object_type"],
                "severity": row["severity"],
                "occurred_at": row["occurred_at"],
                "summary": row["summary"],
                "evidence_refs": [],
                "sensitive_categories": set(),
            },
        )
        if row["projection_id"]:
            signal["evidence_refs"].append(row["projection_id"])
        if row["risk_type"] == "sensitive_object_touch":
            signal["sensitive_categories"].update(_sensitive_categories_for_projection(row["projection_json"], row["raw_content"]))

    grouped: dict[tuple[str, str], dict] = {}
    for signal in signals.values():
        object_type = _normalized_object_type(signal["risk_type"], signal["object_type"], signal["sensitive_categories"])
        if not object_type:
            continue
        key = (signal["risk_type"], object_type)
        item = grouped.setdefault(
            key,
            {
                "risk_type": signal["risk_type"],
                "object_type": object_type,
                "count": 0,
                "highest_severity": signal["severity"],
                "evidence_refs": [],
                "trend": [],
                "top_examples": [],
                "first_seen_at": signal["occurred_at"],
                "last_seen_at": signal["occurred_at"],
            },
        )
        item["count"] += 1
        item["trend"].append({"occurred_at": signal["occurred_at"], "severity": signal["severity"]})
        item["evidence_refs"].extend(signal["evidence_refs"])
        if signal["summary"] not in item["top_examples"] and len(item["top_examples"]) < 3:
            item["top_examples"].append(signal["summary"])
        item["first_seen_at"] = min(item["first_seen_at"], signal["occurred_at"])
        item["last_seen_at"] = max(item["last_seen_at"], signal["occurred_at"])
        if _severity_rank(signal["severity"]) > _severity_rank(item["highest_severity"]):
            item["highest_severity"] = signal["severity"]
    signals = list(grouped.values())
    signals.sort(key=lambda item: (_severity_rank(item["highest_severity"]), item["count"], item["last_seen_at"]), reverse=True)
    if mode == "detailed":
        return {"mode": "detailed", "window": window, "signals": signals}
    return {
        "mode": "summary",
        "window": window,
        "signals": [
            {
                "risk_type": item["risk_type"],
                "object_type": item["object_type"],
                "count": item["count"],
                "highest_severity": item["highest_severity"],
                "top_examples": item["top_examples"],
                "first_seen_at": item["first_seen_at"],
                "last_seen_at": item["last_seen_at"],
            }
            for item in signals
        ],
    }


def _window_cutoff(window: str) -> datetime | None:
    now = datetime.now(UTC)
    if window == "1h":
        return now - timedelta(hours=1)
    if window == "24h":
        return now - timedelta(hours=24)
    if window == "7d":
        return now - timedelta(days=7)
    return None


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalized_object_type(risk_type: str, object_type: str, categories: set[str]) -> str:
    if risk_type != "sensitive_object_touch":
        return object_type
    if not categories and object_type in {"credential", "auth"}:
        return ""
    if object_type == "credential" and categories == {"auth"}:
        return "auth"
    if not object_type and categories:
        if categories.intersection({"token", "secret", "credential", "cookie"}):
            return "credential"
        if "auth" in categories:
            return "auth"
    return object_type


def _sensitive_categories_for_projection(projection_json: str | None, raw_content: str | None) -> set[str]:
    projection = _loads(projection_json)
    categories = projection.get("sensitive_categories")
    if isinstance(categories, list):
        normalized = {str(category) for category in categories if str(category) != "sensitive_reference"}
        if normalized:
            return normalized
    if raw_content:
        return set(sensitive_categories_from_text(raw_content))
    return set()


def _loads(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _severity_rank(severity: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 0)
