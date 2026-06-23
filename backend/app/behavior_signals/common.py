from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from app.time_ranges import window_cutoff_iso


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(value: str | None) -> dict:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def snapshot_hash(value: dict) -> str:
    stable = {key: item for key, item in value.items() if key != "reason"}
    return hashlib.sha256(dumps(stable).encode("utf-8")).hexdigest()


def signal_id(signal_key: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", signal_key).strip("-").lower()
    return f"signal-{slug[:96]}"


def window_cutoff(window: str) -> str | None:
    return window_cutoff_iso(window)
