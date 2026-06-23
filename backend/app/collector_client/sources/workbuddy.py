from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from app.collector_client.config import SourceConfig
from app.collector_client.sources.base import SourceResult, stamp_source
from app.collector_client.telemetry_utils import clean, hash_value, ref
from app.collector_client.usage_contract import normalized_usage_projection, usage_signal_from_projection

SOURCE_KIND = "workbuddy_local"


def collect_workbuddy_source(
    config: SourceConfig,
    *,
    collector_id: str,
    sequence: int,
    telemetry_mode: str,
    history_window_days: int,
    max_events: int,
    cursor: dict,
) -> SourceResult:
    if not config.root.exists():
        return SourceResult(config, "source_missing", "source_missing", [])
    facts: list[dict] = []
    usage_keys = set(str(key) for key in cursor.setdefault("usage_keys", []) if key)
    records = _records(config.root, cursor, max_events=max(1, max_events), history_window_days=history_window_days)
    for source_key, path, line, record in records:
        if len(facts) >= max(1, max_events):
            break
        fact = _fact(config, collector_id, sequence, source_key, path, line, record, usage_keys)
        if fact:
            facts.append(fact)
    cursor["usage_keys"] = sorted(usage_keys)[-5000:]
    return SourceResult(config, "online", "collected", stamp_source(facts, config))


def _records(root: Path, cursor: dict, *, max_events: int, history_window_days: int) -> Iterable[tuple[str, Path, int, dict]]:
    emitted = 0
    cutoff = datetime.now(UTC) - timedelta(days=max(1, history_window_days))
    cursor.setdefault("sources", {})
    for path in _candidate_files(root, cutoff):
        if emitted >= max_events:
            break
        suffix = path.suffix.lower()
        path_hash = hash_value(path.as_posix())
        file_state = _file_state(cursor, path_hash)
        try:
            stat = path.stat()
        except OSError:
            continue
        if suffix in {".jsonl", ".ndjson"}:
            for line, offset, record in _jsonl_records(path, int(file_state.get("byte_offset") or 0), int(file_state.get("line_no") or 0)):
                source_key = f"{path.as_posix()}:{line:08d}"
                yield source_key, path, line, record
                emitted += 1
                file_state.update({"path": path.as_posix(), "size": stat.st_size, "mtime": stat.st_mtime, "byte_offset": offset, "line_no": line})
                cursor["sources"][path_hash] = file_state
                if emitted >= max_events:
                    break
        elif not _fully_consumed(file_state, stat):
            record = _json_file(path)
            if record is not None:
                source_key = f"{path.as_posix()}:00000001"
                yield source_key, path, 1, record
                emitted += 1
            file_state.update({"path": path.as_posix(), "size": stat.st_size, "mtime": stat.st_mtime, "byte_offset": stat.st_size, "line_no": 1})
            cursor["sources"][path_hash] = file_state


def _candidate_files(root: Path, cutoff: datetime) -> list[Path]:
    allowed_roots = ["projects", "traces", "audit-log", "tasks", "sessions"]
    paths: list[tuple[int, float, Path]] = []
    for name in allowed_roots:
        base = root / name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".ndjson"}:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if datetime.fromtimestamp(stat.st_mtime, UTC) >= cutoff:
                priority = allowed_roots.index(name)
                paths.append((priority, -stat.st_mtime, path))
    paths.sort(key=lambda item: (item[0], item[1], item[2].as_posix()))
    return [path for _, _, path in paths]


def _file_state(cursor: dict, path_hash: str) -> dict:
    sources = cursor.setdefault("sources", {})
    state = sources.get(path_hash) if isinstance(sources, dict) else None
    return state if isinstance(state, dict) else {"size": 0, "mtime": 0.0, "byte_offset": 0, "line_no": 0}


def _fully_consumed(file_state: dict, stat: object) -> bool:
    return (
        int(file_state.get("size") or 0) == int(getattr(stat, "st_size", 0) or 0)
        and float(file_state.get("mtime") or 0) == float(getattr(stat, "st_mtime", 0) or 0)
        and int(file_state.get("byte_offset") or 0) >= int(getattr(stat, "st_size", 0) or 0)
    )


def _jsonl_records(path: Path, byte_offset: int, line_no: int) -> Iterable[tuple[int, int, dict]]:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, byte_offset))
            offset = max(0, byte_offset)
            current_line = max(0, line_no)
            while line := handle.readline():
                offset += len(line)
                current_line += 1
                try:
                    payload = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    yield current_line, offset, payload
    except OSError:
        return


def _json_file(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return {"items": payload} if isinstance(payload, list) else None


def _fact(
    config: SourceConfig,
    collector_id: str,
    sequence: int,
    source_key: str,
    path: Path,
    line: int,
    record: dict,
    usage_keys: set[str],
) -> dict | None:
    rel = _relative_kind(config.root, path)
    if rel == "projects":
        return _project_fact(config, collector_id, sequence, source_key, path, line, record, usage_keys)
    if rel == "traces":
        return _trace_fact(config, collector_id, sequence, source_key, path, line, record, usage_keys)
    if rel == "audit-log":
        return _audit_fact(config, collector_id, sequence, source_key, path, line, record)
    if rel == "tasks":
        return _task_fact(config, collector_id, sequence, source_key, path, line, record)
    if rel == "sessions":
        return None
    return None


def _project_fact(
    config: SourceConfig,
    collector_id: str,
    sequence: int,
    source_key: str,
    path: Path,
    line: int,
    record: dict,
    usage_keys: set[str],
) -> dict:
    base = _common(config, collector_id, sequence, source_key, path, line, record, "project_event")
    event_type = clean(record.get("type") or record.get("eventType") or record.get("kind") or "")
    role = clean(record.get("role") or "unknown")
    text = _text(record.get("content") or record.get("text") or record.get("message"))
    lowered_type = event_type.lower()
    usage_projection = _project_usage_projection(record)
    if usage_projection:
        usage_keys.update(_project_usage_keys(record))
    if role == "reasoning" or "reasoning" in lowered_type:
        fact = {
            **base,
            "fact_type": "content",
            "category": "agent_reasoning",
            "quality": "high" if text else "low",
            "severity": "low",
            "summary": "记录到 WorkBuddy 推理过程，已上传原始内容。",
            "projection": {"role": "reasoning", "reasoning_text": text, "content_length": len(text), "raw_content_uploaded": True},
        }
        return _with_usage(fact, usage_projection)
    if _is_tool_result(event_type):
        tool_name = _tool_name(record)
        result_text = _text(record.get("output") or record.get("result") or record.get("content") or record.get("message"))
        fact = {
            **base,
            "fact_type": "tool",
            "category": "tool_result",
            "quality": "high",
            "severity": "low",
            "summary": f"WorkBuddy 工具结果已采集：{tool_name}。",
            "projection": {"tool_name": tool_name, "result_excerpt": result_text[:240], "raw_content_uploaded": True},
        }
        return _with_usage(fact, usage_projection)
    if _is_tool_call(event_type):
        tool_name = _tool_name(record)
        command = _text(record.get("command") or record.get("arguments") or record.get("args") or record.get("input"))
        fact = {
            **base,
            "fact_type": "tool",
            "category": "tool_call",
            "quality": "high",
            "severity": "low",
            "summary": f"WorkBuddy 工具调用已采集：{tool_name}。",
            "projection": {"tool_name": tool_name, "command_excerpt": command[:240], "raw_content_uploaded": True},
        }
        return _with_usage(fact, usage_projection)
    if role in {"user", "assistant"} or text:
        category = "agent_prompt" if role == "user" else "agent_response"
        fact = {
            **base,
            "fact_type": "content",
            "category": category,
            "quality": "high" if text else "low",
            "severity": "low",
            "summary": "记录到 WorkBuddy 会话消息，已上传原始内容。",
            "projection": {"role": role, "content_text": text, "content_length": len(text), "raw_content_uploaded": True},
        }
        return _with_usage(fact, usage_projection)
    if usage_projection:
        return _usage_fact(base, usage_projection, "WorkBuddy project 记录到模型调用用量。")
    return _unknown_fact(base, "WorkBuddy project 事件未归类，已保留原文。")


def _is_tool_call(event_type: str) -> bool:
    return event_type.lower() in {"function_call", "tool_call", "custom_tool_call", "mcp_tool_call", "command_call"}


def _is_tool_result(event_type: str) -> bool:
    return event_type.lower() in {
        "function_call_result",
        "function_call_output",
        "tool_result",
        "tool_call_result",
        "custom_tool_call_output",
        "mcp_tool_result",
        "command_result",
    }


def _tool_name(record: dict) -> str:
    return clean(record.get("name") or record.get("tool") or record.get("toolName") or record.get("functionName") or "unknown_tool")


def _with_usage(fact: dict, usage_projection: dict | None) -> dict:
    if not usage_projection:
        return fact
    projection = dict(fact.get("projection") or {})
    projection.update(usage_projection)
    fact["projection"] = projection
    fact["usage"] = _usage_signal(fact, usage_projection)
    return fact


def _usage_fact(base: dict, projection: dict, summary: str) -> dict:
    units = int(projection.get("units") or 0)
    return {
        **base,
        "fact_type": "usage",
        "category": "usage",
        "quality": "high" if projection.get("observability_level") == "full" else "low",
        "severity": "medium" if units >= 100 else "low",
        "summary": summary,
        "projection": projection,
        "usage": _usage_signal(base, projection),
    }


def _usage_signal(fact: dict, projection: dict) -> dict:
    refs = fact["source_refs"]
    return usage_signal_from_projection(
        projection,
        scope="session",
        session_id=str(refs.get("session_ref") or "unknown"),
        conversation_id=str(refs.get("conversation_ref") or "unknown"),
        project_ref=str(refs.get("workspace_id") or refs.get("workspace_path") or "unknown"),
        account_ref="local",
    )


def _project_usage_projection(record: dict) -> dict | None:
    provider_data = record.get("providerData") if isinstance(record.get("providerData"), dict) else {}
    usage = provider_data.get("usage") if isinstance(provider_data.get("usage"), dict) else {}
    raw_usage = provider_data.get("rawUsage") if isinstance(provider_data.get("rawUsage"), dict) else {}
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    message_usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    if not any((usage, raw_usage, message_usage)):
        return None
    input_tokens = _first_int(message_usage.get("input_tokens"), usage.get("inputTokens"), raw_usage.get("prompt_tokens"))
    output_tokens = _first_int(message_usage.get("output_tokens"), usage.get("outputTokens"), raw_usage.get("completion_tokens"))
    total_tokens = _first_int(message_usage.get("total_tokens"), usage.get("totalTokens"), raw_usage.get("total_tokens"))
    cached_input_tokens = _first_int(
        message_usage.get("cache_read_input_tokens"),
        raw_usage.get("prompt_cache_hit_tokens"),
        _nested_int(raw_usage, "prompt_tokens_details", "cached_tokens"),
        _details_sum(usage.get("inputTokensDetails"), "cached_tokens"),
    )
    cache_write_input_tokens = _first_int(raw_usage.get("prompt_cache_write_tokens"), raw_usage.get("cache_creation_input_tokens"))
    reasoning_output_tokens = _first_int(
        _nested_int(raw_usage, "completion_tokens_details", "reasoning_tokens"),
        _details_sum(usage.get("outputTokensDetails"), "reasoning_tokens"),
    )
    if not any((input_tokens, output_tokens, total_tokens)):
        return None
    return normalized_usage_projection(
        activity_tag="workbuddy_turn",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_input_tokens=cache_write_input_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        model=provider_data.get("model") or provider_data.get("requestModelName") or provider_data.get("requestModelId") or record.get("model"),
        provider=provider_data.get("provider") or provider_data.get("agent") or record.get("provider"),
        credit=raw_usage.get("credit"),
        cache_observed=_has_any_key(message_usage, "cache_read_input_tokens")
        or _has_any_key(raw_usage, "prompt_cache_hit_tokens", "prompt_tokens_details", "cache_creation_input_tokens", "prompt_cache_write_tokens")
        or _details_has_key(usage.get("inputTokensDetails"), "cached_tokens"),
        raw_usage=_raw_usage_summary(usage, raw_usage, message_usage),
    )


def _trace_usage_projection(record: dict) -> dict | None:
    trace = record.get("trace") if isinstance(record.get("trace"), dict) else {}
    model_info = trace.get("modelInfo") if isinstance(trace.get("modelInfo"), dict) else {}
    input_tokens = _first_int(model_info.get("totalInputTokens"))
    output_tokens = _first_int(model_info.get("totalOutputTokens"))
    cached_input_tokens = _first_int(model_info.get("totalCachedTokens"))
    total_tokens = _first_int(trace.get("totalTokens"), trace.get("total_tokens"), record.get("totalTokens"), record.get("total_tokens"))
    if not any((input_tokens, output_tokens, total_tokens)):
        return None
    return normalized_usage_projection(
        activity_tag="workbuddy_turn",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_input_tokens,
        model=",".join(str(item) for item in model_info.get("models", []) if item) if isinstance(model_info.get("models"), list) else "",
        provider=trace.get("agentName") or "",
        cache_observed=bool(model_info) and "totalCachedTokens" in model_info,
        raw_usage={
            "trace_id": trace.get("traceId"),
            "call_count": _int(model_info.get("callCount")),
            "source": "trace.modelInfo" if model_info else "trace.totalTokens",
        },
    )


def _project_usage_keys(record: dict) -> set[str]:
    provider_data = record.get("providerData") if isinstance(record.get("providerData"), dict) else {}
    return _usage_correlation_keys(provider_data, record)


def _trace_usage_keys(record: dict) -> set[str]:
    trace = record.get("trace") if isinstance(record.get("trace"), dict) else {}
    return _usage_correlation_keys(trace, record)


def _usage_correlation_keys(*containers: dict) -> set[str]:
    fields = ("traceId", "trace_id", "conversationRequestId", "conversation_request_id", "requestId", "request_id")
    keys: set[str] = set()
    for container in containers:
        if not isinstance(container, dict):
            continue
        for field in fields:
            value = container.get(field)
            if value:
                keys.add(str(value))
    return keys


def _raw_usage_summary(usage: dict, raw_usage: dict, message_usage: dict) -> dict:
    return {
        "provider_usage": {key: usage.get(key) for key in ("requests", "inputTokens", "outputTokens", "totalTokens") if key in usage},
        "raw_usage": {
            key: raw_usage.get(key)
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "prompt_cache_hit_tokens",
                "prompt_cache_write_tokens",
                "cache_creation_input_tokens",
                "credit",
            )
            if key in raw_usage
        },
        "message_usage": {key: message_usage.get(key) for key in ("input_tokens", "output_tokens", "total_tokens", "cache_read_input_tokens") if key in message_usage},
    }


def _first_int(*values: object) -> int:
    for value in values:
        if value is not None:
            return _int(value)
    return 0


def _nested_int(value: dict, key: str, nested_key: str) -> int | None:
    child = value.get(key) if isinstance(value.get(key), dict) else None
    if child is None or nested_key not in child:
        return None
    return _int(child.get(nested_key))


def _details_sum(value: object, key: str) -> int | None:
    if not isinstance(value, list):
        return None
    total = sum(_int(item.get(key)) for item in value if isinstance(item, dict) and key in item)
    return total if total else 0


def _has_any_key(value: dict, *keys: str) -> bool:
    return any(key in value for key in keys)


def _details_has_key(value: object, key: str) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) and key in item for item in value)


def _trace_fact(
    config: SourceConfig,
    collector_id: str,
    sequence: int,
    source_key: str,
    path: Path,
    line: int,
    record: dict,
    usage_keys: set[str],
) -> dict:
    base = _common(config, collector_id, sequence, source_key, path, line, record, "trace")
    trace_keys = _trace_usage_keys(record)
    if trace_keys and trace_keys.intersection(usage_keys):
        return _unknown_fact(base, "WorkBuddy trace 已采集，project usage 已覆盖该模型调用。")
    projection = _trace_usage_projection(record)
    if projection:
        usage_keys.update(trace_keys)
        return _usage_fact(base, projection, "WorkBuddy trace 记录到 fallback 模型调用用量。")
    return _unknown_fact(base, "WorkBuddy trace 已采集，未发现可汇总 token 字段。")


def _audit_fact(config: SourceConfig, collector_id: str, sequence: int, source_key: str, path: Path, line: int, record: dict) -> dict:
    base = _common(config, collector_id, sequence, source_key, path, line, record, "audit_event")
    event_type = clean(record.get("eventType") or record.get("category") or "audit")
    decision = clean(record.get("decision") or "")
    command = str(record.get("commandPreview") or "")
    if decision in {"denied", "blocked", "rejected"}:
        return {
            **base,
            "fact_type": "risk",
            "category": "destructive_operation",
            "quality": "high",
            "severity": "high",
            "summary": f"WorkBuddy audit 拒绝了本地操作：{event_type}。",
            "projection": {"operation": event_type, "command_excerpt": command[:240], "decision": decision},
            "risk": {"risk_type": "destructive_operation", "severity": "high", "object_type": "command"},
        }
    return {
        **base,
        "fact_type": "tool",
        "category": "tool_call",
        "quality": "high",
        "severity": "low",
        "summary": f"WorkBuddy audit 记录工具或权限事件：{event_type}。",
        "projection": {"tool_name": event_type, "command_excerpt": command[:240], "decision": decision, "raw_content_uploaded": True},
    }


def _task_fact(config: SourceConfig, collector_id: str, sequence: int, source_key: str, path: Path, line: int, record: dict) -> dict:
    base = _common(config, collector_id, sequence, source_key, path, line, record, "task")
    status = clean(record.get("status") or "unknown")
    subject = _text(record.get("subject") or record.get("description"))
    return {
        **base,
        "fact_type": "unknown",
        "category": "task_status",
        "quality": "low",
        "severity": "low",
        "summary": f"WorkBuddy task 状态为 {status}。",
        "projection": {"status": status, "subject": subject[:240], "raw_content_uploaded": True},
    }


def _unknown_fact(base: dict, summary: str) -> dict:
    try:
        raw = json.loads(str(base.get("raw_content") or "{}"))
    except json.JSONDecodeError:
        raw = {}
    keys = sorted(str(key) for key in raw.keys())[:12] if isinstance(raw, dict) else []
    return {
        **base,
        "fact_type": "unknown",
        "category": "uncategorized",
        "quality": "low",
        "severity": "low",
        "summary": summary,
        "projection": {"observed_keys": keys, "raw_content_uploaded": True},
    }


def _common(config: SourceConfig, collector_id: str, sequence: int, source_key: str, path: Path, line: int, record: dict, event_type: str) -> dict:
    session = str(record.get("sessionId") or record.get("session_id") or record.get("session") or path.parent.name or path.stem)
    raw_content = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    source_path_hash = hash_value(path.as_posix())[:16]
    fact_id = f"workbuddy-{hash_value(source_path_hash, line, event_type, raw_content)[:32]}"
    return {
        "source_event_id": fact_id,
        "fact_type": "unknown",
        "category": "uncategorized",
        "quality": "low",
        "severity": "low",
        "summary": "WorkBuddy 事件已采集。",
        "occurred_at": _occurred_at(record),
        "raw_hash": hash_value(raw_content),
        "span": f"workbuddy:{hash_value(source_key)[:12]}",
        "source_refs": {
            "collector_id": collector_id,
            "sequence": sequence,
            "source_key": source_key,
            "source_path_hash": source_path_hash,
            "line": line,
            "conversation_ref": ref(session),
            "session_ref": ref(session),
            "workspace_path": str(record.get("cwd") or ""),
        },
        "source_specific": {"event_type": event_type, "source_template": f"workbuddy.local.{_relative_kind(config.root, path)}.v1"},
        "upload_raw": True,
        "raw_content": raw_content,
    }


def _relative_kind(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).parts[0]
    except ValueError:
        return "unknown"


def _occurred_at(record: dict) -> str:
    raw = record.get("timestamp") or record.get("createdAt") or record.get("created_at") or record.get("updatedAt")
    if isinstance(raw, (int, float)):
        value = raw / 1000 if raw > 10_000_000_000 else raw
        return datetime.fromtimestamp(value, UTC).replace(microsecond=0).isoformat()
    if isinstance(raw, str) and raw:
        return raw
    return _now()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _text(item)))
    if isinstance(value, dict):
        for key in ("text", "content", "message", "prompt", "summary", "description", "command", "output", "result"):
            if key in value and (text := _text(value[key])):
                return text
    return ""


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


collect = collect_workbuddy_source
