from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from app.time_ranges import window_cutoff_iso

_TRACEBACK_PATTERNS = re.compile(r"traceback|raise\s+\w+error|raise\s+\w+exception|\w*(?:Error|Exception):", re.IGNORECASE)
_IMPORT_ERROR_PATTERNS = re.compile(r"module not found|cannot import|no module named|import error|moduleNotFoundError", re.IGNORECASE)
_FILE_ERROR_PATTERNS = re.compile(r"file not found|no such file|directory not found|permission denied|fileNotFoundError|no such directory", re.IGNORECASE)
_COMMAND_CATEGORIES = {
    "test": re.compile(r"\b(pytest|vitest|jest|mocha)\b", re.IGNORECASE),
    "lint": re.compile(r"\b(tsc|eslint|prettier|mypy|flake8|ruff)\b", re.IGNORECASE),
    "build": re.compile(r"\b(npm\s+run\s+build|yarn\s+build|vite\s+build|webpack)\b", re.IGNORECASE),
}


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


def classify_tool_failure(reason: str, envelope_body: str) -> dict:
    """Classify a tool failure into a precise sub-type and compute priority.

    Returns a dict with keys:
      - sub_type: one of 'workflow_gate_blocked', 'validation_failure',
                  'tool_crash', 'tool_fallback'
      - priority: integer priority score
      - detail: human-readable description
    """
    # 1. Workflow gate blocked
    try:
        gate = json.loads(reason)
        if isinstance(gate, dict) and gate.get("blocked") is True:
            return {
                "sub_type": "workflow_gate_blocked",
                "priority": 30,
                "detail": "Workflow gate blocked",
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Extract a limited snippet for pattern matching (first 2000 chars)
    snippet = (envelope_body or "")[:2000]

    # 2. Validation failure (test/lint/build command failure)
    for cmd_cat, pat in _COMMAND_CATEGORIES.items():
        if pat.search(snippet):
            return {
                "sub_type": "validation_failure",
                "priority": 60,
                "detail": f"Command category: {cmd_cat}",
            }

    # 3. Tool crash (specific error patterns)
    if _IMPORT_ERROR_PATTERNS.search(snippet):
        return {
            "sub_type": "tool_crash",
            "priority": 95,
            "detail": "Import/module resolution error",
        }
    if _FILE_ERROR_PATTERNS.search(snippet):
        return {
            "sub_type": "tool_crash",
            "priority": 95,
            "detail": "File/directory not found or permission denied",
        }
    if _TRACEBACK_PATTERNS.search(snippet):
        return {
            "sub_type": "tool_crash",
            "priority": 95,
            "detail": "Runtime traceback/exception",
        }

    # 4. Fallback
    return {
        "sub_type": "tool_fallback",
        "priority": 70,
        "detail": "Unmatched failure pattern",
    }
