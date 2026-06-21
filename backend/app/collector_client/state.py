from __future__ import annotations

import json
import threading
from pathlib import Path

_STATE_LOCK = threading.RLock()


def load_state(path: Path) -> dict:
    with _STATE_LOCK:
        if not path.exists():
            return _default_state()
        state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("schema_version", 2)
    state.setdefault("cursor", {})
    state["cursor"].setdefault("last_sequence", 0)
    state["cursor"].setdefault("sources", {})
    state["cursor"].setdefault("backfill", {})
    state.setdefault("outbox", [])
    state.setdefault("last_upload_at", None)
    state.setdefault("last_error", None)
    state.setdefault("running", False)
    state.setdefault("runtime_phase", "idle")
    state.setdefault("reason_code", "started")
    state.setdefault("source_status", "offline")
    return state


def save_state(path: Path, state: dict) -> None:
    with _STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        state.setdefault("schema_version", 2)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)


def patch_state(path: Path, fields: dict) -> dict:
    with _STATE_LOCK:
        state = load_state(path)
        state.update(fields)
        save_state(path, state)
        return state


def _default_state() -> dict:
    return {
        "schema_version": 2,
        "running": False,
        "runtime_phase": "idle",
        "reason_code": "started",
        "source_status": "offline",
        "cursor": {
            "last_sequence": 0,
            "sources": {},
            "backfill": {},
        },
        "outbox": [],
        "last_upload_at": None,
        "last_error": None,
    }
