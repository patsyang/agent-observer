from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

SENSITIVE_MARKERS = {"token", "cookie", "secret", "auth", "credential"}


def payload(record: dict) -> dict:
    value = record.get("payload")
    return value if isinstance(value, dict) else {}


def top_type(record: dict) -> str:
    return clean(record.get("type") or record.get("event_type") or record.get("kind") or "unknown")


def payload_type(record: dict) -> str:
    value = payload(record)
    return clean(value.get("type") or record.get("type") or record.get("event_type") or record.get("kind") or "unknown")


def event_type(record: dict, value: dict) -> str:
    root_type = top_type(record)
    nested_type = clean(value.get("type") or "")
    return f"{root_type}:{nested_type}" if nested_type else root_type


def arguments(value: dict) -> dict:
    raw = value.get("arguments") or value.get("input") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def exit_code(record: dict) -> int | None:
    value = payload(record)
    for candidate in (record.get("exit_code"), record.get("code"), value.get("exit_code"), value.get("code")):
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    output = value.get("output")
    if isinstance(output, str):
        match = re.search(r"Exit code:\s*(-?\d+)", output)
        if match:
            return int(match.group(1))
    if payload_type(record) == "patch_apply_end" and value.get("success") is False:
        return 1
    return None


def safe_signature_seed(record: dict) -> str:
    value = payload(record)
    args = arguments(value)
    output = value.get("output")
    return dumps_safe(
        {
            "top_type": top_type(record),
            "payload_type": payload_type(record),
            "tool": value.get("name") or record.get("tool"),
            "command_category": command_category(str(args.get("command", ""))),
            "call_ref": hash_value(str(value.get("call_id", "")))[:16] if value.get("call_id") else None,
            "output_shape": hash_value(str(output))[:16] if output is not None else None,
        }
    )


def activity_tags(record: dict) -> list[str]:
    value = payload_type(record)
    if value == "token_count":
        return ["codex_turn"]
    if value in {"function_call", "custom_tool_call"}:
        return ["tool_call"]
    return ["unknown"]


def command_category(command: str) -> str:
    lowered = command.lower()
    if not lowered:
        return ""
    if re.search(r"\b(rm|del|erase|rmdir)\b|remove-item|git\s+reset\s+--hard|git\s+clean\b", lowered):
        return "destructive"
    if "chmod" in lowered or "permission" in lowered:
        return "permission_change"
    if any(term in lowered for term in ("pytest", "vitest", "playwright test", "npm test", "npm run test")):
        return "test"
    if any(term in lowered for term in ("npm run build", "tsc", "vite build")):
        return "build"
    if lowered.strip().startswith("git "):
        return "git"
    if any(term in lowered for term in ("rg ", "select-string", "findstr")):
        return "search"
    if any(term in lowered for term in ("get-content", "type ", "cat ")):
        return "file_read"
    if re.search(r"\b(npm|pip|python -m pip)\b", lowered):
        return "package"
    return "shell"


def change_count(value: dict) -> int:
    changes = value.get("changes")
    if isinstance(changes, dict):
        return len(changes)
    if isinstance(changes, list):
        return len(changes)
    return 0


def object_type(path: str) -> str:
    lowered = path.lower()
    if any(part in lowered for part in ("config", ".env", "auth", "credential")):
        return "configuration"
    if any(part in lowered for part in ("test", "spec")):
        return "test"
    if path:
        return "workspace_file"
    return "workspace"


def occurred_at(record: dict) -> str:
    raw = record.get("timestamp") or record.get("created_at") or record.get("time")
    if isinstance(raw, str) and raw:
        return raw
    return now()


def codex_home(codex_home_value: str | Path | None = None) -> Path:
    if codex_home_value is not None:
        return Path(codex_home_value)
    if env := os.environ.get("CODEX_HOME"):
        return Path(env)
    return Path.home() / ".codex"


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def clean(value: object) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(value or "unknown"))
    return cleaned[:80] or "unknown"


def safe_key(value: object) -> str:
    lowered = clean(value).lower()
    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return "sensitive_field"
    return lowered[:60]


def ref(value: object) -> str:
    return f"ref:{hash_value(str(value or 'unknown'))[:16]}"


def stable_projection(record: dict, *, include_values: bool) -> str:
    if include_values:
        return json.dumps(record, sort_keys=True, default=str)
    return json.dumps(sorted(safe_key(key) for key in record.keys()), sort_keys=True)


def dumps_safe(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def hash_value(*parts: object) -> str:
    return hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()
