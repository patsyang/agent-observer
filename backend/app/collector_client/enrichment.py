from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.collector_client.command_context import command_error_projection
from app.collector_client.config import CollectorConfig
from app.collector_client.source_reader import _incremental_records
from app.collector_client.telemetry_utils import hash_value as _hash
from app.collector_client.telemetry_utils import occurred_at as _occurred_at
from app.collector_client.telemetry_utils import payload as _payload


COMMAND_ID = "collect_codex_tool_failure_context"
OUTPUT_SCHEMA = "tool_failure_context.v1"


def run_enrichment(config: CollectorConfig, job: dict[str, Any]) -> dict[str, Any]:
    command = job.get("command") if isinstance(job.get("command"), dict) else {}
    if command.get("command_id") != COMMAND_ID:
        return {
            "status": "unavailable",
            "summary": "内置补证任务中不存在该能力。",
            "projection": {"reason_code": "missing_capability"},
            "redaction": _redaction(),
        }

    sessions_dir = Path(config.codex_home) / "sessions"
    if not sessions_dir.exists():
        return {
            "status": "unavailable",
            "summary": "本机 Codex 会话目录不存在，无法补充工具失败上下文。",
            "projection": {"reason_code": "source_missing"},
            "redaction": _redaction(),
        }

    rows = _session_rows(sessions_dir, config)
    failures = _matched_failures(rows, _target_refs(command))
    if not failures:
        return {
            "status": "failed",
            "summary": "未在本机 Codex 会话中找到可补充的失败工具调用上下文。",
            "projection": {
                "capability_id": job.get("capability_id"),
                "output_schema": OUTPUT_SCHEMA,
                "reason_code": "tool_failure_context_not_found",
                "searched_event_count": len(rows),
                "matched_conversations": [],
                "matched_failures": [],
                "redaction": _redaction(),
            },
            "redaction": _redaction(),
        }

    conversations = _matched_conversations(rows, failures)
    return {
        "status": "succeeded",
        "summary": f"已补充 {len(failures)} 条工具失败上下文，关联 {len(conversations)} 个会话。",
        "projection": {
            "capability_id": job.get("capability_id"),
            "output_schema": OUTPUT_SCHEMA,
            "matched_conversations": conversations,
            "matched_failures": failures[:20],
            "redaction": _redaction(),
        },
        "redaction": _redaction(),
    }


def _target_refs(command: dict[str, Any]) -> dict[str, set[Any]]:
    refs = command.get("evidence_refs")
    targets = {"path_lines": set(), "conversations": set()}
    if not isinstance(refs, list):
        return targets
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        path_hash = str(ref.get("source_path_hash") or "")
        line = ref.get("source_line")
        if path_hash and line is not None:
            try:
                targets["path_lines"].add((path_hash, int(line)))
            except (TypeError, ValueError):
                pass
        conversation_ref = str(ref.get("conversation_ref") or "")
        if conversation_ref:
            targets["conversations"].add(conversation_ref)
    return targets


def _session_rows(sessions_dir: Path, config: CollectorConfig) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, int(config.history_window_days)))
    cursor: dict[str, Any] = {"sources": {}}
    limit = max(500, int(config.max_events_per_cycle) * 5)
    rows = []
    for source_key, path, line_number, record in _incremental_records(sessions_dir, cutoff, cursor, limit):
        rows.append({"source_key": source_key, "path": path, "line_number": line_number, "record": record})
    rows.sort(key=lambda item: (str(item["path"]), int(item["line_number"])))
    return rows


def _matched_failures(rows: list[dict[str, Any]], targets: dict[str, set[Any]]) -> list[dict[str, Any]]:
    failures = []
    for index, row in enumerate(rows):
        projection = command_error_projection(row["record"])
        if not projection or int(projection.get("exit_code") or 0) == 0:
            continue
        if not _matches_target(row, targets):
            continue
        record = row["record"]
        output = str(_payload(record).get("output") or "")
        failure = {
            "tool_name": projection.get("tool_name") or "function_call",
            "call_id": projection.get("call_id") or "",
            "exit_code": projection.get("exit_code"),
            "command_excerpt": _excerpt(str(projection.get("command") or "")),
            "output_excerpt": _excerpt(output),
            "occurred_at": _occurred_at(record),
            "source_event_ref": {
                "source_key": row["source_key"],
                "line": row["line_number"],
                "source_path_hash": _hash(Path(row["path"]).as_posix())[:16],
            },
            "conversation_ref": _conversation_ref(record, Path(row["path"])),
            "token_usage": _token_usage_for_conversation(rows, _conversation_ref(record, Path(row["path"]))),
            "surrounding_messages": _surrounding_messages(rows, index),
        }
        failures.append(failure)
    failures.sort(key=lambda item: str(item["occurred_at"]), reverse=True)
    return failures


def _matches_target(row: dict[str, Any], targets: dict[str, set[Any]]) -> bool:
    path_lines = targets.get("path_lines") or set()
    conversations = targets.get("conversations") or set()
    if not path_lines and not conversations:
        return True
    path_hash = _hash(Path(row["path"]).as_posix())[:16]
    if (path_hash, int(row["line_number"])) in path_lines:
        return True
    return _conversation_ref(row["record"], Path(row["path"])) in conversations


def _matched_conversations(rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for failure in failures:
        ref = str(failure.get("conversation_ref") or "")
        if ref and ref not in refs:
            refs.append(ref)
    conversations = []
    for ref in refs[:20]:
        messages = _conversation_messages(rows, ref)
        conversations.append(
            {
                "conversation_ref": ref,
                "prompt_excerpt": next((item["content_excerpt"] for item in messages if item["role"] == "user"), ""),
                "response_excerpt": next((item["content_excerpt"] for item in messages if item["role"] == "assistant"), ""),
                "token_usage": _token_usage_for_conversation(rows, ref),
                "matched_failure_count": sum(1 for item in failures if item.get("conversation_ref") == ref),
            }
        )
    return conversations


def _surrounding_messages(rows: list[dict[str, Any]], index: int) -> list[dict[str, str]]:
    path = rows[index]["path"]
    window = [item for item in rows[max(0, index - 8) : index + 9] if item["path"] == path]
    messages = []
    for item in window:
        message = _message(item["record"])
        if message:
            messages.append(message)
    return messages[-6:]


def _conversation_messages(rows: list[dict[str, Any]], conversation_ref: str) -> list[dict[str, str]]:
    messages = []
    for row in rows:
        if _conversation_ref(row["record"], Path(row["path"])) != conversation_ref:
            continue
        message = _message(row["record"])
        if message:
            messages.append(message)
    return messages


def _message(record: dict[str, Any]) -> dict[str, str] | None:
    payload = _payload(record)
    role = str(payload.get("role") or record.get("role") or "")
    event_type = str(payload.get("type") or record.get("type") or "")
    if event_type in {"user_message", "input_text"}:
        role = "user"
    if event_type in {"assistant_message", "message", "response_item"} and role != "user":
        role = role or "assistant"
    if role not in {"user", "assistant"}:
        return None
    content = _content_text(payload) or _content_text(record)
    if not content:
        return None
    return {"role": role, "content_excerpt": _excerpt(content), "occurred_at": _occurred_at(record)}


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(part for item in value if (part := _content_text(item)))
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "message", "prompt", "output", "result"):
        text = _content_text(value.get(key))
        if text:
            return text
    return _content_text(value.get("payload"))


def _token_usage_for_conversation(rows: list[dict[str, Any]], conversation_ref: str) -> dict[str, int]:
    total = 0
    for row in rows:
        record = row["record"]
        if _conversation_ref(record, Path(row["path"])) != conversation_ref:
            continue
        payload = _payload(record)
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        last_usage = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
        units = record.get("total_tokens") or record.get("tokens") or record.get("units") or last_usage.get("total_tokens") or 0
        try:
            total += int(units)
        except (TypeError, ValueError):
            continue
    return {"effective_units": total}


def _conversation_ref(record: dict[str, Any], path: Path) -> str:
    payload = _payload(record)
    return str(
        record.get("conversation_id")
        or record.get("conversation")
        or payload.get("turn_id")
        or record.get("session_id")
        or record.get("session")
        or path.stem
    )


def _excerpt(value: str, limit: int = 600) -> str:
    normalized = " ".join(str(value or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}..."


def _redaction() -> dict[str, bool]:
    return {
        "raw_content_uploaded": False,
        "prompt_uploaded": False,
        "response_uploaded": False,
    }
