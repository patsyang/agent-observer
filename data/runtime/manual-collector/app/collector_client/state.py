from __future__ import annotations

import json
from pathlib import Path


def load_state(path: Path) -> dict:
    if not path.exists():
        return {
            "running": False,
            "cursor": {"last_sequence": 0, "last_source_key": ""},
            "outbox": [],
            "last_upload_at": None,
            "last_error": None,
            "raw_upload_enabled": False,
        }
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("cursor", {})
    state["cursor"].setdefault("last_sequence", 0)
    state["cursor"].setdefault("last_source_key", "")
    state.setdefault("outbox", [])
    state.setdefault("last_upload_at", None)
    state.setdefault("last_error", None)
    state.setdefault("running", False)
    state.setdefault("raw_upload_enabled", False)
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
