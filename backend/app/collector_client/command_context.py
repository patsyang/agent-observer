from __future__ import annotations

from typing import Iterable

from app.collector_client.telemetry_utils import command_category as categorize_command
from app.collector_client.tool_execution import (
    arguments_from_payload,
    command_excerpt,
    command_fingerprint,
    command_text,
    error_excerpt,
    parse_tool_output,
    workflow_identity,
)


def attach_call_context(records: Iterable[tuple[int, dict]]) -> list[tuple[int, dict]]:
    rows = [(line_number, dict(record)) for line_number, record in records]
    calls: dict[str, dict] = {}
    for line_number, record in rows:
        payload = _payload(record)
        if payload.get("type") != "function_call":
            continue
        call_id = str(payload.get("call_id") or "")
        if call_id:
            calls[call_id] = {"line": line_number, "record": record, "arguments": arguments_from_payload(payload)}
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
        return _standalone_output_projection(record)
    call_record = call.get("record")
    if not isinstance(call_record, dict):
        return None
    call_payload = _payload(call_record)
    args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    return _projection_from_output(payload, call_payload, args)


def tool_failure_fact(common: dict, projection: dict) -> dict:
    if projection.get("exit_code") == 0:
        raise ValueError("successful_tool_output_cannot_be_failure")
    category = "workflow_step_timeout" if projection.get("timeout_type") == "workflow_step_timeout" else None
    category = category or "tool_execution_timeout" if projection.get("is_timeout") else category
    category = category or "workflow_step_failure" if projection.get("workflow") and projection.get("run_id") else category
    category = category or "tool_execution_failure"
    severity = "high" if projection.get("is_timeout") or projection.get("workflow") else "medium"
    summary = _summary(category, projection)
    signature = _signature(category, projection)
    return {
        **common,
        "fact_type": "error",
        "category": category,
        "quality": "high" if projection.get("command") else "medium",
        "severity": severity,
        "summary": summary,
        "projection": {**projection, "signature": signature},
        "error_signature": {"signature_key": signature, "category": category},
    }


def _projection_from_output(payload: dict, call_payload: dict, args: dict) -> dict | None:
    output = str(payload.get("output") or "")
    envelope = parse_tool_output(output)
    if envelope.exit_code is None or envelope.exit_code == 0:
        return None
    command = command_text(args)
    workflow, run_id = workflow_identity(command)
    timeout_type = "workflow_step_timeout" if envelope.is_timeout and workflow else "tool_execution_timeout" if envelope.is_timeout else None
    return {
        "is_timeout": envelope.is_timeout,
        "timeout_type": timeout_type,
        "tool_name": str(call_payload.get("name") or "function_call"),
        "command": command,
        "command_excerpt": command_excerpt(command),
        "command_fingerprint": command_fingerprint(command),
        "command_category": categorize_command(command),
        "workdir": str(args.get("workdir") or ""),
        "timeout_ms": _int_or_none(args.get("timeout_ms")),
        "exit_code": envelope.exit_code,
        "wall_time_seconds": envelope.wall_time_seconds,
        "timeout_after_ms": envelope.timeout_after_ms,
        "workflow": workflow,
        "run_id": run_id,
        "call_id": str(payload.get("call_id") or ""),
        "error_excerpt": error_excerpt(output),
        "output_source": "tool_envelope",
    }


def _standalone_output_projection(record: dict) -> dict | None:
    payload = _payload(record)
    if payload.get("type") != "function_call_output":
        return None
    projection = _projection_from_output(payload, {"name": "function_call_output"}, {})
    if projection is None or projection.get("exit_code") == 0:
        return None
    return projection


def _summary(category: str, projection: dict) -> str:
    duration = projection.get("wall_time_seconds")
    duration_text = f"{duration:,.0f} 秒" if isinstance(duration, (float, int)) else "未知时长"
    command = projection.get("command_excerpt") or projection.get("tool_name") or "工具调用"
    if category == "workflow_step_timeout":
        return f"Workflow 步骤超时：{projection.get('workflow')} / {projection.get('run_id')}，运行约 {duration_text}。"
    if category == "workflow_step_failure":
        return f"Workflow 步骤失败：{projection.get('workflow')} / {projection.get('run_id')}，exit_code={projection.get('exit_code')}。"
    if category == "tool_execution_timeout":
        return f"工具执行超时：{command}，运行约 {duration_text}。"
    return f"工具执行失败：{command}，exit_code={projection.get('exit_code')}。"


def _signature(category: str, projection: dict) -> str:
    if projection.get("workflow") and projection.get("run_id"):
        return f"{category}:{projection.get('workflow')}:{projection.get('run_id')}:{projection.get('exit_code')}"
    fingerprint = projection.get("command_fingerprint") or projection.get("tool_name") or "unknown"
    return f"{category}:{projection.get('tool_name')}:{fingerprint}:{projection.get('exit_code')}"


def _payload(record: dict) -> dict:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
