from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolOutputEnvelope:
    exit_code: int | None
    wall_time_seconds: float | None
    timeout_after_ms: int | None
    body: str

    @property
    def is_failure(self) -> bool:
        return self.exit_code is not None and self.exit_code != 0

    @property
    def is_timeout(self) -> bool:
        return self.exit_code == 124


def parse_tool_output(output: str) -> ToolOutputEnvelope:
    envelope, body = _split_output(str(output or ""))
    process_match = re.search(r"^Process exited with code\s+(-?\d+)\s*$", envelope, re.MULTILINE)
    old_match = re.search(r"^Exit code:\s*(-?\d+)\s*$", envelope, re.MULTILINE)
    exit_code = _int(process_match.group(1)) if process_match else _int(old_match.group(1)) if old_match else None
    wall_match = re.search(r"^Wall time:\s*([0-9.]+)\s*seconds\s*$", envelope, re.MULTILINE)
    timeout_match = re.search(r"timed out after\s*(\d+)\s*milliseconds", body if exit_code == 124 else "", re.IGNORECASE)
    return ToolOutputEnvelope(
        exit_code=exit_code,
        wall_time_seconds=_float(wall_match.group(1)) if wall_match else None,
        timeout_after_ms=_int(timeout_match.group(1)) if timeout_match else None,
        body=body,
    )


def command_text(args: dict) -> str:
    return str(args.get("cmd") or args.get("command") or "").strip()


def command_fingerprint(command: str) -> str:
    normalized = " ".join(str(command or "").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else ""


def command_excerpt(command: str, limit: int = 500) -> str:
    text = " ".join(str(command or "").split())
    return text if len(text) <= limit else f"{text[:limit - 1]}..."


def error_excerpt(output: str, limit: int = 500) -> str:
    body = parse_tool_output(output).body
    text = _strip_ansi(body).strip()
    if not text:
        text = _strip_ansi(str(output or "")).strip()
    return text[:limit]


def arguments_from_payload(payload: dict) -> dict:
    raw = payload.get("arguments") or payload.get("input") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def workflow_identity(command: str) -> tuple[str | None, str | None]:
    workflow = None
    run_id = None
    workflow_match = re.search(r"\bao\.py\s+([a-z-]+)\s+(?:run|resume|execute)\b", command)
    if workflow_match:
        workflow = workflow_match.group(1)
    run_match = re.search(r"--run-id\s+([A-Za-z0-9_-]+)", command)
    if run_match:
        run_id = run_match.group(1)
    return workflow, run_id


def _split_output(output: str) -> tuple[str, str]:
    match = re.search(r"(?m)^Output:\s*$", output)
    if not match:
        return output, ""
    return output[: match.start()], output[match.end() :].lstrip("\r\n")


def _strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", value)


def _int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
