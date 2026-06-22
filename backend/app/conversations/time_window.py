from __future__ import annotations

from datetime import UTC, datetime, timedelta


def window_cutoff(window: str) -> str | None:
    if window == "all":
        return None
    if window == "today":
        local_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return local_start.astimezone(UTC).isoformat()
    hours = {"1h": 1, "2h": 2, "3h": 3, "24h": 24, "7d": 24 * 7}.get(window)
    if hours is None:
        return None
    return (datetime.now(UTC) - timedelta(hours=hours)).replace(microsecond=0).isoformat()


def normalize_iso_param(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat()
