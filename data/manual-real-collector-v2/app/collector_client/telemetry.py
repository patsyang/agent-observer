from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable


HIGH_RISK_OPERATIONS = {"delete", "remove", "rm", "overwrite", "chmod", "permission_change"}
SENSITIVE_MARKERS = {"token", "cookie", "secret", "auth", "credential"}
CONTENT_EVENTS = {"message", "reasoning", "agent_message", "user_message"}


def collect_sanitized_facts(
    collector_id: str,
    sequence: int,
    telemetry_mode: str,
    *,
    codex_home: str | Path | None = None,
    history_window_days: int = 7,
    max_events: int = 500,
    cursor: dict | None = None,
) -> list[dict]:
    observed_at = _now()
    root = _codex_home(codex_home)
    sessions_dir = root / "sessions"
    facts = [_health_fact(collector_id, sequence, observed_at, telemetry_mode, sessions_dir.exists())]
    source_facts = _codex_facts(
        collector_id=collector_id,
        sequence=sequence,
        codex_home=root,
        history_window_days=history_window_days,
        max_events=max_events,
        last_source_key=str((cursor or {}).get("last_source_key", "")),
    )
    if source_facts:
        return facts + source_facts
    return facts + [_source_gap_fact(collector_id, sequence, observed_at, telemetry_mode, sessions_dir.exists())]


def _codex_facts(
    *,
    collector_id: str,
    sequence: int,
    codex_home: Path,
    history_window_days: int,
    max_events: int,
    last_source_key: str,
) -> list[dict]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=max(1, history_window_days))
    facts: list[dict] = []
    for source_key, path, line_number, record in _records(sessions_dir, cutoff):
        if source_key <= last_source_key:
            continue
        fact = _record_fact(collector_id, sequence, source_key, path, line_number, record)
        if fact:
            facts.append(fact)
        if len(facts) >= max(1, max_events):
            break
    return facts


def _records(sessions_dir: Path, cutoff: datetime) -> Iterable[tuple[str, Path, int, dict]]:
    paths = sorted(
        path for path in sessions_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".jsonl", ".json", ".ndjson"}
    )
    for path in paths:
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_number, record in _parse_records(text):
            source_key = f"{path.as_posix()}:{line_number:08d}"
            yield source_key, path, line_number, record


def _parse_records(text: str) -> Iterable[tuple[int, dict]]:
    stripped = text.strip()
    if not stripped:
        return
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if isinstance(payload.get("events"), list):
                for index, item in enumerate(payload["events"], 1):
                    if isinstance(item, dict):
                        yield index, item
                return
            yield 1, payload
            return
    for index, line in enumerate(text.splitlines(), 1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield index, payload


def _record_fact(collector_id: str, sequence: int, source_key: str, path: Path, line_number: int, record: dict) -> dict | None:
    payload = _payload(record)
    event_type = _event_type(record, payload)
    occurred_at = _occurred_at(record)
    refs = _source_refs(collector_id, sequence, source_key, path, line_number, record)
    common = {
        "source_event_id": f"codex-{_hash(source_key)[:20]}",
        "occurred_at": occurred_at,
        "span": f"codex-session:{_hash(source_key)[:12]}",
        "raw_hash": _hash(_stable_projection(record, include_values=False)),
        "source_refs": refs,
        "source_specific": {
            "codex_event_type": event_type,
            "source_template": "codex.local.sessions.v1",
            "validation_sample": record.get("validation_sample"),
        },
    }
    if _is_usage(record):
        return _usage_fact(common, record)
    if _is_error(record):
        return _error_fact(common, record)
    if risk := _risk_fact(common, record):
        return risk
    if tool := _tool_fact(common, record):
        return tool
    if _has_sensitive_marker(record):
        return _sensitive_fact(common, record)
    if _payload_type(record) in CONTENT_EVENTS:
        return None
    return _low_evidence_fact(common, record)


def _error_fact(common: dict, record: dict) -> dict:
    payload = _payload(record)
    tool = _clean(record.get("tool") or record.get("command") or payload.get("name") or _payload_type(record) or "unknown_tool")
    phase = _clean(record.get("phase") or payload.get("status") or record.get("status") or _top_type(record))
    exit_code = _exit_code(record) or 1
    signature_seed = _safe_signature_seed(record)
    signature = f"codex_error:{tool}:{phase}:{exit_code}:{_hash(signature_seed)[:8]}"
    return {
        **common,
        "fact_type": "error",
        "category": "codex_error",
        "quality": "high",
        "severity": "high" if exit_code else "medium",
        "summary": f"Codex {tool} 在 {phase} 阶段失败，exit_code={exit_code}，已生成脱敏错误签名。",
        "projection": {"tool": tool, "phase": phase, "exit_code": exit_code, "signature": signature},
        "error_signature": {"signature_key": signature, "category": "codex_error"},
    }


def _usage_fact(common: dict, record: dict) -> dict:
    payload = _payload(record)
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    last_usage = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
    units = int(
        record.get("total_tokens")
        or record.get("tokens")
        or record.get("units")
        or last_usage.get("total_tokens")
        or 0
    )
    tags = record.get("activity_tags") or record.get("activity_tag") or _activity_tags(record)
    if isinstance(tags, str):
        activity_tag = _clean(tags)
    elif isinstance(tags, list) and tags:
        activity_tag = _clean(tags[0])
    else:
        activity_tag = "unknown"
    session_id = _ref(record.get("session_id") or record.get("session") or payload.get("turn_id") or "unknown")
    conversation_id = _ref(record.get("conversation_id") or record.get("conversation") or payload.get("turn_id") or "unknown")
    return {
        **common,
        "fact_type": "usage",
        "category": "usage",
        "quality": "high" if activity_tag != "unknown" else "low",
        "severity": "medium" if units >= 100 else "low",
        "summary": f"Codex 会话产生 {units} token 相关用量，活动标签为 {activity_tag}。",
        "projection": {
            "units": units,
            "activity_tag": activity_tag,
            "tag_count": len(tags) if isinstance(tags, list) else 1,
            "model_context_window": int(info.get("model_context_window") or 0),
        },
        "usage": {
            "scope": "session",
            "units": units,
            "activity_tag": activity_tag,
            "usage_kind": "attributed" if record.get("attributed") else "associated",
            "session_id": session_id,
            "conversation_id": conversation_id,
            "project_ref": _ref(record.get("project") or "unknown"),
            "account_ref": _ref(record.get("account") or "local"),
        },
    }


def _risk_fact(common: dict, record: dict) -> dict | None:
    payload = _payload(record)
    args = _arguments(payload)
    command_category = _command_category(str(args.get("command", "")))
    operation = _clean(record.get("operation") or record.get("action") or args.get("operation") or payload.get("name") or record.get("tool") or "")
    path = _clean(record.get("path") or record.get("target") or args.get("path") or args.get("workdir") or "")
    patch_risk = _payload_type(record) == "patch_apply_end" and bool(payload.get("success"))
    if operation not in HIGH_RISK_OPERATIONS and command_category != "destructive" and "delete" not in path and "auth" not in path.lower() and not patch_risk:
        return None
    object_type = _object_type(path)
    return {
        **common,
        "fact_type": "risk",
        "category": "high_risk_operation",
        "quality": "high",
        "severity": "medium",
        "summary": f"检测到高风险本地操作类别：{operation or command_category or 'workspace_change'}，对象类型 {object_type}。",
        "projection": {
            "operation": operation or command_category or "workspace_change",
            "object_type": object_type,
            "path_hash": _hash(path)[:16],
            "command_category": command_category,
            "change_count": _change_count(payload),
        },
        "risk": {"risk_type": "high_risk_operation", "severity": "medium", "object_type": object_type},
    }


def _sensitive_fact(common: dict, record: dict) -> dict:
    return {
        **common,
        "fact_type": "risk",
        "category": "sensitive_touch",
        "quality": "high",
        "severity": "high",
        "summary": "Codex 会话触达敏感对象类别，已仅上报分类投影和计数。",
        "projection": {"object_type": "credential", "category_count": len(_sensitive_categories(record))},
        "risk": {"risk_type": "sensitive_object_touch", "severity": "high", "object_type": "credential"},
    }


def _low_evidence_fact(common: dict, record: dict) -> dict:
    payload = _payload(record)
    return {
        **common,
        "fact_type": "unknown",
        "category": "uncategorized",
        "quality": "low",
        "severity": "low",
        "summary": "Codex 会话出现未归类但来源合法的低证据事件，已保留为事实查询候选。",
        "projection": {
            "observed_keys": sorted(_safe_key(key) for key in record.keys())[:12],
            "payload_type": _payload_type(record),
            "payload_keys": sorted(_safe_key(key) for key in payload.keys())[:12],
        },
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
    tool_name = _clean(payload.get("name") or payload_type)
    command_category = _command_category(str(args.get("command", "")))
    exit_code = _exit_code(record)
    if exit_code and exit_code != 0:
        return None
    return {
        **common,
        "fact_type": "tool",
        "category": "tool_call" if "call_output" not in payload_type else "tool_result",
        "quality": "high",
        "severity": "low",
        "summary": f"Codex 调用工具 {tool_name}，类别 {command_category or payload_type}，仅记录结构化投影。",
        "projection": {
            "tool_name": tool_name,
            "payload_type": payload_type,
            "command_category": command_category,
            "argument_keys": sorted(_safe_key(key) for key in args.keys())[:12],
            "workdir_hash": _hash(str(args.get("workdir", "")))[:16] if args.get("workdir") else None,
            "exit_code": exit_code,
            "raw_content_uploaded": False,
        },
    }


def _health_fact(collector_id: str, sequence: int, observed_at: str, telemetry_mode: str, source_available: bool) -> dict:
    return {
        "source_event_id": f"{collector_id}-health-{sequence}",
        "fact_type": "collector_health",
        "category": "collector_health",
        "quality": "high",
        "severity": "low",
        "summary": "采集器完成一次本机链路自检，状态、游标和 outbox 已结构化上报。",
        "occurred_at": observed_at,
        "raw_hash": _hash("health", collector_id, sequence, observed_at, telemetry_mode),
        "span": "collector:self-check",
        "source_refs": {"collector_id": collector_id, "sequence": sequence, "source_key": f"health:{sequence}"},
        "source_specific": {"telemetry_mode": telemetry_mode, "probe": "collector_self_check"},
        "projection": {
            "collector_id": collector_id,
            "cursor_sequence": sequence,
            "codex_session_dir_present": source_available,
            "uploaded_raw_content": False,
        },
    }


def _source_gap_fact(collector_id: str, sequence: int, observed_at: str, telemetry_mode: str, source_available: bool) -> dict:
    status = "已检测到 Codex 会话目录，但本轮没有发现新的可投影事件。"
    severity = "low"
    if not source_available:
        status = "未检测到 Codex 会话目录，当前只能上传最小化链路自检摘要。"
        severity = "high"
    return {
        "source_event_id": f"{collector_id}-source-status-{sequence}",
        "fact_type": "collector_health",
        "category": "collector_source_status",
        "quality": "high",
        "severity": severity,
        "summary": f"{status} 未上传原始日志、提示词、令牌或认证信息。",
        "occurred_at": observed_at,
        "raw_hash": _hash("source-status", collector_id, sequence, observed_at, telemetry_mode, str(source_available)),
        "span": "collector:source-probe",
        "source_refs": {"collector_id": collector_id, "sequence": sequence, "source_key": f"source-status:{sequence}"},
        "source_specific": {"telemetry_mode": telemetry_mode, "probe": "codex_session_dir_presence"},
        "projection": {"source_kind": "codex_sessions", "source_available": source_available, "raw_content_uploaded": False},
    }


def _source_refs(collector_id: str, sequence: int, source_key: str, path: Path, line_number: int, record: dict) -> dict:
    payload = _payload(record)
    return {
        "collector_id": collector_id,
        "sequence": sequence,
        "source_key": source_key,
        "source_path_hash": _hash(path.as_posix())[:16],
        "line": line_number,
        "conversation_ref": _ref(record.get("conversation_id") or record.get("conversation") or payload.get("turn_id") or source_key),
        "session_ref": _ref(record.get("session_id") or record.get("session") or payload.get("id") or path.stem),
    }


def _is_error(record: dict) -> bool:
    payload = _payload(record)
    status = str(record.get("status") or record.get("level") or payload.get("status") or "").lower()
    if status in {"error", "failed", "failure"}:
        return True
    if _payload_type(record) == "patch_apply_end" and payload.get("success") is False:
        return True
    if (_payload_type(record) in {"function_call_output", "custom_tool_call_output"}) and (_exit_code(record) or 0) != 0:
        return True
    try:
        return int(record.get("exit_code") or 0) != 0
    except (TypeError, ValueError):
        return False


def _is_usage(record: dict) -> bool:
    if any(key in record for key in ("total_tokens", "tokens", "units", "activity_tag", "activity_tags")):
        return True
    payload = _payload(record)
    return _payload_type(record) == "token_count" and isinstance(payload.get("info"), dict)


def _has_sensitive_marker(record: dict) -> bool:
    return bool(_sensitive_categories(record))


def _sensitive_categories(record: dict) -> set[str]:
    values = set()
    payload = _payload(record)
    args = _arguments(payload)
    categories = record.get("sensitive_categories") or []
    if isinstance(categories, str):
        categories = [categories]
    for category in categories:
        if str(category).lower() in SENSITIVE_MARKERS:
            values.add(str(category).lower())
    for key in record:
        if any(marker in str(key).lower() for marker in SENSITIVE_MARKERS):
            values.add(str(key).lower())
    for value in (args.get("command"), args.get("path"), args.get("workdir"), payload.get("name")):
        lowered = str(value or "").lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            values.add("sensitive_reference")
    return values


def _payload(record: dict) -> dict:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _top_type(record: dict) -> str:
    return _clean(record.get("type") or record.get("event_type") or record.get("kind") or "unknown")


def _payload_type(record: dict) -> str:
    payload = _payload(record)
    return _clean(payload.get("type") or record.get("type") or record.get("event_type") or record.get("kind") or "unknown")


def _event_type(record: dict, payload: dict) -> str:
    top_type = _top_type(record)
    payload_type = _clean(payload.get("type") or "")
    return f"{top_type}:{payload_type}" if payload_type else top_type


def _arguments(payload: dict) -> dict:
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


def _exit_code(record: dict) -> int | None:
    payload = _payload(record)
    for value in (record.get("exit_code"), record.get("code"), payload.get("exit_code"), payload.get("code")):
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    output = payload.get("output")
    if isinstance(output, str):
        match = re.search(r"Exit code:\s*(-?\d+)", output)
        if match:
            return int(match.group(1))
    if _payload_type(record) == "patch_apply_end" and payload.get("success") is False:
        return 1
    return None


def _safe_signature_seed(record: dict) -> str:
    payload = _payload(record)
    args = _arguments(payload)
    output = payload.get("output")
    return _dumps_safe(
        {
            "top_type": _top_type(record),
            "payload_type": _payload_type(record),
            "tool": payload.get("name") or record.get("tool"),
            "command_category": _command_category(str(args.get("command", ""))),
            "call_ref": _hash(str(payload.get("call_id", "")))[:16] if payload.get("call_id") else None,
            "output_shape": _hash(str(output))[:16] if output is not None else None,
        }
    )


def _activity_tags(record: dict) -> list[str]:
    payload_type = _payload_type(record)
    if payload_type == "token_count":
        return ["codex_turn"]
    if payload_type in {"function_call", "custom_tool_call"}:
        return ["tool_call"]
    return ["unknown"]


def _command_category(command: str) -> str:
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


def _change_count(payload: dict) -> int:
    changes = payload.get("changes")
    if isinstance(changes, dict):
        return len(changes)
    if isinstance(changes, list):
        return len(changes)
    return 0


def _object_type(path: str) -> str:
    lowered = path.lower()
    if any(part in lowered for part in ("config", ".env", "auth", "credential")):
        return "configuration"
    if any(part in lowered for part in ("test", "spec")):
        return "test"
    if path:
        return "workspace_file"
    return "workspace"


def _occurred_at(record: dict) -> str:
    raw = record.get("timestamp") or record.get("created_at") or record.get("time")
    if isinstance(raw, str) and raw:
        return raw
    return _now()


def _codex_home(codex_home: str | Path | None = None) -> Path:
    if codex_home is not None:
        return Path(codex_home)
    if env := os.environ.get("CODEX_HOME"):
        return Path(env)
    return Path.home() / ".codex"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _clean(value: object) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(value or "unknown"))
    return cleaned[:80] or "unknown"


def _safe_key(value: object) -> str:
    lowered = _clean(value).lower()
    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return "sensitive_field"
    return lowered[:60]


def _ref(value: object) -> str:
    return f"ref:{_hash(str(value or 'unknown'))[:16]}"


def _stable_projection(record: dict, *, include_values: bool) -> str:
    if include_values:
        return json.dumps(record, sort_keys=True, default=str)
    return json.dumps(sorted(_safe_key(key) for key in record.keys()), sort_keys=True)


def _dumps_safe(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(*parts: object) -> str:
    return hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()
