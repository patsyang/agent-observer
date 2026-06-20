from __future__ import annotations

import json
import re
from typing import Iterable


def attach_call_context(records: Iterable[tuple[int, dict]]) -> list[tuple[int, dict]]:
    rows = [(line_number, dict(record)) for line_number, record in records]
    calls: dict[str, dict] = {}
    for line_number, record in rows:
        payload = _payload(record)
        if payload.get("type") != "function_call":
            continue
        call_id = str(payload.get("call_id") or "")
        if call_id:
            calls[call_id] = {"line": line_number, "record": record, "arguments": _arguments(payload)}
    enriched: list[tuple[int, dict]] = []
    for line_number, record in rows:
        payload = _payload(record)
        call_id = str(payload.get("call_id") or "")
        if payload.get("type") == "function_call_output" and call_id in calls:
            record = dict(record)
            record["_agent_observer_call"] = calls[call_id]
        enriched.append((line_number, record))
    return enriched


def command_error_projection(record: dict) -> dict | None:
    payload = _payload(record)
    call = record.get("_agent_observer_call")
    if not isinstance(call, dict):
        return None
    call_record = call.get("record")
    if not isinstance(call_record, dict):
        return None
    call_payload = _payload(call_record)
    args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    output = str(payload.get("output") or "")
    exit_code = _exit_code(output)
    if exit_code is None:
        return None
    wall_time_seconds = _wall_time_seconds(output)
    timeout_after_ms = _timeout_after_ms(output)
    command = str(args.get("command") or "")
    workflow, run_id = _workflow_identity(command)
    timeout = exit_code == 124 or timeout_after_ms is not None or "timed out" in output.lower()
    return {
        "is_timeout": timeout,
        "tool_name": str(call_payload.get("name") or "function_call"),
        "command": command,
        "workdir": str(args.get("workdir") or ""),
        "timeout_ms": _int_or_none(args.get("timeout_ms")),
        "exit_code": exit_code,
        "wall_time_seconds": wall_time_seconds,
        "timeout_after_ms": timeout_after_ms,
        "workflow": workflow,
        "run_id": run_id,
        "call_id": str(payload.get("call_id") or ""),
    }


def command_timeout_fact(common: dict, projection: dict) -> dict:
    workflow = projection.get("workflow") or "unknown"
    run_id = projection.get("run_id") or "unknown"
    duration = projection.get("wall_time_seconds")
    duration_text = f"{duration:,.0f} 秒" if isinstance(duration, (float, int)) else "未知时长"
    signature = f"command_timeout:{workflow}:{run_id}:{projection.get('exit_code')}"
    return {
        **common,
        "fact_type": "error",
        "category": "command_timeout",
        "quality": "high",
        "severity": "high",
        "summary": f"{workflow} resume 在 {run_id} 上运行约 {duration_text}后超时退出。",
        "projection": {
            "tool": projection["tool_name"],
            "tool_name": projection["tool_name"],
            "command": projection["command"],
            "workdir": projection["workdir"],
            "timeout_ms": projection["timeout_ms"],
            "exit_code": projection["exit_code"],
            "wall_time_seconds": projection["wall_time_seconds"],
            "timeout_after_ms": projection["timeout_after_ms"],
            "workflow": workflow,
            "run_id": run_id,
            "call_id": projection["call_id"],
            "signature": signature,
        },
        "error_signature": {"signature_key": signature, "category": "command_timeout"},
    }


def _payload(record: dict) -> dict:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _arguments(payload: dict) -> dict:
    raw = payload.get("arguments") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _exit_code(output: str) -> int | None:
    match = re.search(r"Exit code:\s*(-?\d+)", output)
    return int(match.group(1)) if match else None


def _wall_time_seconds(output: str) -> float | None:
    match = re.search(r"Wall time:\s*([0-9.]+)\s*seconds", output)
    return float(match.group(1)) if match else None


def _timeout_after_ms(output: str) -> int | None:
    match = re.search(r"timed out after\s*(\d+)\s*milliseconds", output, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _workflow_identity(command: str) -> tuple[str | None, str | None]:
    workflow = None
    run_id = None
    workflow_match = re.search(r"\bao\.py\s+([a-z-]+)\s+(?:run|resume|execute)\b", command)
    if workflow_match:
        workflow = workflow_match.group(1)
    run_match = re.search(r"--run-id\s+([A-Za-z0-9_-]+)", command)
    if run_match:
        run_id = run_match.group(1)
    return workflow, run_id


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
