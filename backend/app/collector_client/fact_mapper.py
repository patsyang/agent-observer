from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.collector_client.command_context import command_error_projection, tool_failure_fact
from app.collector_client.content_events import CONTENT_EVENTS, content_fact
from app.collector_client.content_dedup import stamp_content_identity
from app.collector_client.telemetry_utils import (
    activity_tags as _activity_tags,
    arguments as _arguments,
    change_count as _change_count,
    clean as _clean,
    command_category as _command_category,
    event_type as _event_type,
    exit_code as _exit_code,
    hash_value as _hash,
    is_semantic_nonzero_exit as _is_semantic_nonzero_exit,
    object_type as _object_type,
    occurred_at as _occurred_at,
    payload as _payload,
    payload_type as _payload_type,
    ref as _ref,
    safe_key as _safe_key,
    stable_projection as _stable_projection,
    top_type as _top_type,
)
from app.collector_client.tool_execution import command_excerpt, command_text
from app.collector_client.usage_contract import normalized_usage_projection, usage_signal_from_projection

DESTRUCTIVE_OPERATIONS = {"delete", "remove", "rm", "overwrite", "chmod", "permission_change"}


def _record_fact(
    collector_id: str,
    sequence: int,
    source_key: str,
    path: Path,
    line_number: int,
    record: dict,
    *,
    session_titles: dict[str, str] | None = None,
    workspace_resolver: Any | None = None,
) -> dict | None:
    payload = _payload(record)
    event_type = _event_type(record, payload)
    occurred_at = _occurred_at(record)
    refs = _source_refs(collector_id, sequence, source_key, path, line_number, record, session_titles or {}, workspace_resolver)
    event_id = _source_event_id(refs["source_path_hash"], line_number, event_type, occurred_at, record)
    common = {
        "source_event_id": event_id,
        "occurred_at": occurred_at,
        "span": f"codex-session:{_hash(source_key)[:12]}",
        "raw_hash": _hash(_stable_projection(record, include_values=False)),
        "source_refs": refs,
        "source_specific": {
            "event_type": event_type,
            "source_template": "codex.local.sessions.v1",
            "validation_sample": record.get("validation_sample"),
        },
        "upload_raw": True,
    }
    common["raw_content"] = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    if _is_usage(record):
        return _usage_fact(common, record)
    if _is_error(record):
        return _error_fact(common, record)
    if change := _file_change_fact(common, record):
        return change
    if risk := _destructive_fact(common, record):
        return risk
    if tool := _tool_fact(common, record):
        return tool
    if _payload_type(record) in CONTENT_EVENTS:
        fact = content_fact(common, record)
        stamp_content_identity(fact, path, record)
        return fact
    if _is_perf(record):
        return _perf_fact(common, record)
    return _low_evidence_fact(common, record)

def _error_fact(common: dict, record: dict) -> dict:
    command_projection = command_error_projection(record)
    if command_projection:
        return tool_failure_fact(common, command_projection)
    payload = _payload(record)
    tool = _clean(record.get("tool") or record.get("command") or payload.get("name") or _payload_type(record) or "unknown_tool")
    phase = _clean(record.get("phase") or payload.get("status") or record.get("status") or _top_type(record))
    exit_code = _exit_code(record) or 1
    error_kind = _clean(record.get("error_kind") or payload.get("error") or payload.get("type") or _payload_type(record))
    signature = f"tool_execution_failure:{tool}:{phase}:{exit_code}:{error_kind}"
    return {
        **common,
        "fact_type": "error",
        "category": "tool_execution_failure",
        "quality": "high",
        "severity": "high" if exit_code else "medium",
        "summary": f"工具执行失败：{tool} 在 {phase} 阶段 exit_code={exit_code}。",
        "projection": {"tool": tool, "phase": phase, "exit_code": exit_code, "error_kind": error_kind, "signature": signature},
        "error_signature": {"signature_key": signature, "category": "tool_execution_failure"},
    }

def _usage_fact(common: dict, record: dict) -> dict:
    payload = _payload(record)
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    last_usage = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
    tags = record.get("activity_tags") or record.get("activity_tag") or _activity_tags(record)
    if isinstance(tags, str):
        activity_tag = _clean(tags)
    elif isinstance(tags, list) and tags:
        activity_tag = _clean(tags[0])
    else:
        activity_tag = "unknown"
    session_id = _ref(record.get("session_id") or record.get("session") or payload.get("turn_id") or "unknown")
    conversation_id = _ref(record.get("conversation_id") or record.get("conversation") or payload.get("turn_id") or "unknown")
    projection = normalized_usage_projection(
        activity_tag=activity_tag,
        input_tokens=last_usage.get("input_tokens"),
        output_tokens=last_usage.get("output_tokens"),
        total_tokens=last_usage.get("total_tokens") or record.get("total_tokens") or record.get("tokens") or record.get("units"),
        cached_input_tokens=last_usage.get("cached_input_tokens"),
        reasoning_output_tokens=last_usage.get("reasoning_output_tokens"),
        model=info.get("model") or record.get("model"),
        provider=info.get("provider") or record.get("provider"),
        cache_observed=bool(last_usage) and "cached_input_tokens" in last_usage,
    )
    projection.update(
        {
            "tag_count": len(tags) if isinstance(tags, list) else 1,
            "model_context_window": int(info.get("model_context_window") or 0),
            "context_total_tokens": _int(last_usage.get("total_tokens")),
        }
    )
    units = int(projection["units"])
    return {
        **common,
        "fact_type": "usage",
        "category": "usage",
        "quality": "high" if activity_tag != "unknown" else "low",
        "severity": "medium" if units >= 100 else "low",
        "summary": f"Agent 会话产生 {units} token 相关用量，活动标签为 {activity_tag}。",
        "projection": projection,
        "usage": usage_signal_from_projection(
            projection,
            scope="session",
            session_id=session_id,
            conversation_id=conversation_id,
            project_ref=common["source_refs"].get("workspace_id") or _ref(record.get("project") or "unknown"),
            account_ref=_ref(record.get("account") or "local"),
        ),
    }

def _effective_usage_units(record: dict, last_usage: dict) -> int:
    explicit = record.get("total_tokens") or record.get("tokens") or record.get("units")
    if explicit is not None:
        return _int(explicit)
    input_tokens = _int(last_usage.get("input_tokens"))
    cached_input_tokens = _int(last_usage.get("cached_input_tokens"))
    output_tokens = _int(last_usage.get("output_tokens"))
    if input_tokens or output_tokens:
        return max(0, input_tokens - cached_input_tokens) + output_tokens
    return _int(last_usage.get("total_tokens"))

def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

def _file_change_fact(common: dict, record: dict) -> dict | None:
    payload = _payload(record)
    if _payload_type(record) != "patch_apply_end" or not bool(payload.get("success")):
        return None
    changes = payload.get("changes")
    if not isinstance(changes, dict) or not changes:
        return None
    paths = [str(path).replace("\\", "/") for path in changes.keys()]
    additions = sum(_int(value.get("additions")) for value in changes.values() if isinstance(value, dict))
    deletions = sum(_int(value.get("deletions")) for value in changes.values() if isinstance(value, dict))
    top_dirs = _top_directories(paths)
    return {
        **common,
        "fact_type": "risk",
        "category": "file_change",
        "quality": "high",
        "severity": "medium",
        "summary": f"Agent 修改了 {len(paths)} 个工作区文件，新增 {additions} 行，删除 {deletions} 行。",
        "projection": {
            "operation": "file_change",
            "object_type": "workspace_file",
            "changed_paths": paths[:200],
            "file_count": len(paths),
            "additions": additions,
            "deletions": deletions,
            "top_directories": top_dirs,
        },
        "risk": {"risk_type": "file_change", "severity": "medium", "object_type": "workspace_file"},
    }


def _destructive_fact(common: dict, record: dict) -> dict | None:
    payload = _payload(record)
    args = _arguments(payload)
    command = command_text(args)
    command_category = _command_category(command)
    operation = _clean(record.get("operation") or record.get("action") or args.get("operation") or payload.get("name") or record.get("tool") or "")
    raw_path = str(record.get("path") or record.get("target") or args.get("path") or args.get("workdir") or "")
    path = _clean(raw_path)
    if operation not in DESTRUCTIVE_OPERATIONS and command_category not in {"destructive", "permission_change"} and not re.search(r"\bdelet(e|ion)\b", raw_path, re.I):
        return None
    object_type = _object_type(path)
    return {
        **common,
        "fact_type": "risk",
        "category": "destructive_operation",
        "quality": "high",
        "severity": "high",
        "summary": f"检测到破坏性本地操作：{operation or command_category}，对象类型 {object_type}。",
        "projection": {
            "operation": operation or command_category,
            "object_type": object_type,
            "command_excerpt": command_excerpt(command),
            "path_hash": _hash(path)[:16],
            "command_category": command_category,
            "change_count": _change_count(payload),
        },
        "risk": {"risk_type": "destructive_operation", "severity": "high", "object_type": object_type},
    }

def _low_evidence_fact(common: dict, record: dict) -> dict:
    payload = _payload(record)
    return {
        **common,
        "fact_type": "unknown",
        "category": "uncategorized",
        "quality": "low",
        "severity": "low",
        "summary": "Agent 会话出现未归类但来源合法的低证据事件，已保留为低证据命中候选。",
        "projection": {
            "observed_keys": sorted(_safe_key(key) for key in record.keys())[:12],
            "payload_type": _payload_type(record),
            "payload_keys": sorted(_safe_key(key) for key in payload.keys())[:12],
        },
    }

# Codex task_complete / turn_aborted 事件：提取 turn 级延迟与 TTFT，写入 perf_signals。
# task_complete.payload: {turn_id, duration_ms, time_to_first_token_ms, completed_at, last_agent_message}
# turn_aborted.payload:  {turn_id, duration_ms, completed_at, reason}  (无 TTFT)
_PERF_EVENT_TYPES = {"task_complete", "turn_aborted"}


def _is_perf(record: dict) -> bool:
    return _payload_type(record) in _PERF_EVENT_TYPES


def _perf_occurred_at(payload: dict, fallback: str) -> str:
    """completed_at 是 Unix 秒，转成 ISO；缺失或异常时回退到 record.timestamp。"""
    raw = payload.get("completed_at")
    try:
        if raw is not None:
            return datetime.fromtimestamp(int(raw), tz=UTC).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return fallback


def _perf_fact(common: dict, record: dict) -> dict:
    payload = _payload(record)
    event_type = _payload_type(record)
    turn_id = str(payload.get("turn_id") or "")
    trace_id = turn_id or _hash(common["source_event_id"])
    task_span_id = f"task-{turn_id[:16]}" if turn_id else f"task-{_hash(common['source_event_id'])[:16]}"
    llm_span_id = f"llm-{turn_id[:16]}" if turn_id else f"llm-{_hash(common['source_event_id'])[:16]}"
    duration_ms = _int(payload.get("duration_ms"))
    # ttft_ms 是 turn 级原始事实：用于 summary、projection、llm_call span。
    # task span 的 ttft_ms 置 0，因为 TTFT 是 LLM generation 指标，应归属 llm_call span。
    ttft_ms = _int(payload.get("time_to_first_token_ms"))  # turn_aborted 无此字段，自然为 0
    status = "ok" if event_type == "task_complete" else "error"
    error = str(payload.get("reason") or "") if event_type == "turn_aborted" else ""
    occurred_at = _perf_occurred_at(payload, common["occurred_at"])
    task_span = {
        "trace_id": trace_id,
        "span_id": task_span_id,
        "parent_span_id": "",
        "span_type": "task",
        "span_name": "codex_turn",
        "duration_ms": duration_ms,
        "ttft_ms": 0,
        "tps": 0.0,
        "status": status,
        "error": error,
        "model": "",
        "tool_name": "",
        "occurred_at": occurred_at,
    }
    # 拆分 llm_call span：codex 一个 turn 在协议层就是一次 generation 调用。
    # duration_ms=0：codex turn 事件只提供 turn 总耗时（含工具调用、等待），
    # 没有 LLM generation duration 字段，不能把 turn duration 当 LLM duration（会显示 23 分钟）。
    # ttft_ms 迁移到这里，使"LLM 调用"的 TTFT 指标有真实值。
    # _latency_stats 会过滤 duration_ms=0 的行，不参与百分位统计。
    llm_span = {
        "trace_id": trace_id,
        "span_id": llm_span_id,
        "parent_span_id": task_span_id,
        "span_type": "llm_call",
        "span_name": "codex_generation",
        "duration_ms": 0,
        "ttft_ms": ttft_ms,
        "tps": 0.0,
        "status": status,
        "error": error,
        "model": "",
        "tool_name": "",
        "occurred_at": occurred_at,
    }
    summary = (
        f"Codex turn 完成，耗时 {duration_ms}ms，TTFT {ttft_ms}ms。"
        if event_type == "task_complete"
        else f"Codex turn 中止（{error or 'unknown'}），耗时 {duration_ms}ms。"
    )
    return {
        **common,
        "fact_type": "perf",
        "category": "agent_turn_latency",
        "quality": "high",
        "severity": "low",
        "summary": summary,
        "projection": {
            "event_type": event_type,
            "turn_id": turn_id,
            "duration_ms": duration_ms,
            "ttft_ms": ttft_ms,
            "status": status,
        },
        "perf_signals": [task_span, llm_span],
    }

def _mcp_args_summary(invocation: dict) -> str:
    """从 invocation.arguments 提取一句话摘要用于列表展示。"""
    args = invocation.get("arguments")
    if not isinstance(args, dict) or not args:
        return ""
    if isinstance(args.get("title"), str) and args["title"]:
        return args["title"][:80]
    if isinstance(args.get("code"), str) and args["code"]:
        first_line = args["code"].split("\n", 1)[0].strip()
        return first_line[:80] or args["code"][:80]
    return json.dumps(args, ensure_ascii=False)[:80]


def _mcp_projection(payload: dict) -> dict | None:
    """从 MCP 事件 payload 提取 server/tool/duration_ms/is_error projection 字段。

    payload.invocation 缺失或非 dict 时返回 None，调用方不追加 MCP 字段。
    duration 缺失时 mcp_duration_ms=0；result 缺失或非 Err 时 mcp_is_error=False。
    """
    invocation = payload.get("invocation")
    if not isinstance(invocation, dict):
        return None
    server = str(invocation.get("server") or "")
    tool = str(invocation.get("tool") or "")
    duration = payload.get("duration")
    duration_ms = 0
    if isinstance(duration, dict):
        duration_ms = int((_int(duration.get("secs")) * 1_000_000_000 + _int(duration.get("nanos"))) / 1_000_000)
    is_error = False
    result = payload.get("result")
    if isinstance(result, dict):
        if "Err" in result:
            is_error = True
        else:
            ok = result.get("Ok")
            if isinstance(ok, dict) and ok.get("isError") is True:
                is_error = True
    return {
        "mcp_server": server,
        "mcp_tool": tool,
        "mcp_duration_ms": duration_ms,
        "mcp_is_error": is_error,
        "mcp_args_summary": _mcp_args_summary(invocation),
    }


def _tool_fact(common: dict, record: dict) -> dict | None:
    payload = _payload(record)
    payload_type = _payload_type(record)
    if payload_type not in {
        "function_call",
        "custom_tool_call",
        "mcp_tool_call_end",
        "function_call_output",
        "custom_tool_call_output",
        "tool_call",
        "tool_result",
    }:
        return None
    args = _arguments(payload)
    call = record.get("_agent_observer_call")
    if isinstance(call, dict) and not args:
        call_args = call.get("arguments")
        if isinstance(call_args, dict):
            args = call_args
    tool_name = _clean(payload.get("name") or payload_type)
    command = command_text(args)
    command_category = _command_category(command)
    exit_code = _exit_code(record)
    if exit_code and exit_code != 0 and not _is_semantic_nonzero_exit(command_category, exit_code):
        return None
    mcp_projection = _mcp_projection(payload) if payload_type == "mcp_tool_call_end" else None
    if mcp_projection and mcp_projection.get("mcp_tool"):
        tool_name = _clean(mcp_projection["mcp_tool"])
    projection = {
        "tool_name": tool_name,
        "payload_type": payload_type,
        "command": command,
        "command_excerpt": command_excerpt(command),
        "command_category": command_category,
        "argument_keys": sorted(_safe_key(key) for key in args.keys())[:12],
        "workdir_hash": _hash(str(args.get("workdir", "")))[:16] if args.get("workdir") else None,
        "exit_code": exit_code,
        "raw_content_uploaded": bool(common.get("upload_raw")),
    }
    if mcp_projection:
        projection.update(mcp_projection)
    return {
        **common,
        "fact_type": "tool",
        "category": "tool_call" if payload_type in {"function_call", "custom_tool_call", "tool_call"} else "tool_result",
        "quality": "high",
        "severity": "low",
        "summary": f"Agent 调用工具 {tool_name}，类别 {command_category or payload_type}，已提取工具调用摘要。",
        "projection": projection,
    }


def _top_directories(paths: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for path in paths:
        directory = "/".join(path.split("/")[:2]) if "/" in path else path
        counts[directory] = counts.get(directory, 0) + 1
    return [path for path, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]]

def _source_refs(
    collector_id: str,
    sequence: int,
    source_key: str,
    path: Path,
    line_number: int,
    record: dict,
    session_titles: dict[str, str] | None = None,
    workspace_resolver: Any | None = None,
) -> dict:
    payload = _payload(record)
    session_ref = record.get("session_id") or record.get("session") or payload.get("id") or path.stem
    # conversation_ref 优先取会话级标识（conversation_id/session_id），
    # turn_id 降级为兜底：避免同一会话按 turn 拆成多个 conversation_ref，
    # 与 materialize.py 的"会话级 ref"设计意图一致。
    conversation_ref = (
        record.get("conversation_id")
        or record.get("conversation")
        or record.get("session_id")
        or record.get("session")
        or payload.get("turn_id")
        or path.stem
    )
    refs = {
        "collector_id": collector_id,
        "sequence": sequence,
        "source_key": source_key,
        "source_path_hash": _hash(path.as_posix())[:16],
        "line": line_number,
        "conversation_ref": _ref(conversation_ref),
        "session_ref": _ref(session_ref),
    }
    if title := _session_title(session_titles or {}, record, payload, path, session_ref):
        refs["session_title"] = title
    if workspace_resolver is not None:
        refs.update({key: value for key, value in workspace_resolver.resolve(path, record).items() if value})
    return refs

def _session_title(session_titles: dict[str, str], record: dict, payload: dict, path: Path, session_ref: object) -> str:
    for candidate in _session_title_candidates(record, payload, path, session_ref):
        title = session_titles.get(candidate)
        if title:
            return title
    return ""

def _session_title_candidates(record: dict, payload: dict, path: Path, session_ref: object) -> list[str]:
    values = [record.get("session_id"), record.get("session"), payload.get("id"), session_ref, path.stem]
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", path.stem, re.IGNORECASE)
    if match:
        values.append(match.group(1))
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result

def _source_event_id(path_hash: str, line_number: int, event_type: str, occurred_at: str, record: dict) -> str:
    native_id = record.get("id") or record.get("event_id") or record.get("call_id")
    if native_id:
        return f"codex-{_hash(path_hash, str(native_id), line_number, event_type)[:32]}"
    content_hash = _hash(_stable_projection(record, include_values=True))
    return f"codex-{_hash(path_hash, line_number, event_type, occurred_at, content_hash)[:32]}"

def _is_error(record: dict) -> bool:
    payload = _payload(record)
    if _payload_type(record) in {"function_call_output", "custom_tool_call_output"}:
        exit_code = _exit_code(record)
        if exit_code is not None and exit_code != 0:
            if _is_semantic_exit(record, payload, exit_code):
                return False
            return True
        if exit_code is not None and exit_code == 0:
            return False
    status = str(record.get("status") or record.get("level") or payload.get("status") or "").lower()
    if status in {"error", "failed", "failure"}:
        return True
    # custom_tool_call_output 自身没有 status 字段，检查关联的 custom_tool_call 的 status。
    # attach_call_context 会把 custom_tool_call 的 record 附加到 _agent_observer_call。
    call = record.get("_agent_observer_call")
    if isinstance(call, dict):
        call_record = call.get("record")
        if isinstance(call_record, dict):
            call_status = str(_payload(call_record).get("status") or "").lower()
            if call_status in {"error", "failed", "failure"}:
                return True
    if _payload_type(record) == "patch_apply_end" and payload.get("success") is False:
        return True
    try:
        return int(record.get("exit_code") or 0) != 0
    except (TypeError, ValueError):
        return False


def _is_semantic_exit(record: dict, payload: dict, exit_code: int) -> bool:
    """Check if a non-zero exit_code is a semantic result, not an execution error."""
    args = _arguments(payload)
    call = record.get("_agent_observer_call")
    if isinstance(call, dict) and not args:
        call_args = call.get("arguments")
        if isinstance(call_args, dict):
            args = call_args
    command = command_text(args)
    if not command:
        return False
    cat = _command_category(command)
    return _is_semantic_nonzero_exit(cat, exit_code)

def _is_usage(record: dict) -> bool:
    if any(key in record for key in ("total_tokens", "tokens", "units", "activity_tag", "activity_tags")):
        return True
    payload = _payload(record)
    return _payload_type(record) == "token_count" and isinstance(payload.get("info"), dict)
