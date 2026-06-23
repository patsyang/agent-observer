from __future__ import annotations

from datetime import UTC, datetime, timedelta


HOUR_WINDOWS = {
    "1h": 1,
    "2h": 2,
    "3h": 3,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "7d": 24 * 7,
}


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_iso(value: str | None) -> str | None:
    parsed = parse_iso(value)
    if parsed is None:
        return value or None
    return parsed.replace(microsecond=0).isoformat()


def window_cutoff(window: str) -> datetime | None:
    if window == "all":
        return None
    if window == "today":
        local_now = datetime.now().astimezone()
        return local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    if window == "week":
        local_now = datetime.now().astimezone()
        local_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return (local_today - timedelta(days=local_today.weekday())).astimezone(UTC)
    hours = HOUR_WINDOWS.get(window)
    if hours is None:
        return None
    return datetime.now(UTC) - timedelta(hours=hours)


def window_cutoff_iso(window: str) -> str | None:
    cutoff = window_cutoff(window)
    return cutoff.replace(microsecond=0).isoformat() if cutoff else None


def range_bounds(window: str, start_at: str | None = None, end_at: str | None = None) -> tuple[datetime | None, datetime | None]:
    return parse_iso(start_at) or window_cutoff(window), parse_iso(end_at)


def range_bounds_iso(window: str, start_at: str | None = None, end_at: str | None = None) -> tuple[str | None, str | None]:
    start, end = range_bounds(window, start_at, end_at)
    return (
        start.replace(microsecond=0).isoformat() if start else None,
        end.replace(microsecond=0).isoformat() if end else None,
    )


def within_range(value: str, window: str, start_at: str | None = None, end_at: str | None = None) -> bool:
    occurred = parse_iso(value)
    if occurred is None:
        return True
    start, end = range_bounds(window, start_at, end_at)
    if start and occurred < start:
        return False
    if end and occurred > end:
        return False
    return True


def bucket_size_minutes(window: str, start_at: str | None = None, end_at: str | None = None) -> int:
    if window == "1h":
        return 1
    if window == "3h":
        return 15
    if window == "6h":
        return 30
    if window in {"12h", "today", "24h"}:
        return 60
    if window in {"week", "7d", "all"}:
        return 24 * 60
    start, end = range_bounds(window, start_at, end_at)
    if start and not end:
        end = datetime.now(UTC)
    if end and not start:
        start = end - timedelta(hours=24)
    if not start or not end:
        return 24 * 60
    seconds = max(0, (end - start).total_seconds())
    if seconds <= 60 * 60:
        return 1
    if seconds <= 6 * 60 * 60:
        return 15
    if seconds <= 24 * 60 * 60:
        return 60
    if seconds <= 14 * 24 * 60 * 60:
        return 24 * 60
    return 7 * 24 * 60


def bucket_start_iso(value: str, minutes: int) -> str:
    occurred = parse_iso(value)
    if occurred is None:
        return str(value)
    if minutes == 24 * 60:
        local = occurred.astimezone()
        return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).isoformat()
    if minutes == 7 * 24 * 60:
        local_day = occurred.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return (local_day - timedelta(days=local_day.weekday())).astimezone(UTC).isoformat()
    total_minutes = occurred.hour * 60 + occurred.minute
    floored = (total_minutes // minutes) * minutes
    return occurred.replace(hour=floored // 60, minute=floored % 60, second=0, microsecond=0).isoformat()
