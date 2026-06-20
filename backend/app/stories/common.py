from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()

def _loads(value: str) -> dict:
    return json.loads(value or "{}")

def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))

def _snapshot_hash(snapshot: dict) -> str:
    stable_snapshot = {key: value for key, value in snapshot.items() if key != "reason"}
    return hashlib.sha256(_dumps(stable_snapshot).encode("utf-8")).hexdigest()

def _story_id(story_key: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", story_key).strip("-").lower()
    return f"story-{slug[:80]}"

def _window_cutoff(window: str) -> str | None:
    if window == "all":
        return None
    hours = {"1h": 1, "24h": 24, "7d": 24 * 7}.get(window)
    if hours is None:
        return None
    return (datetime.now(UTC) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
