from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from app.collector_client.config import SourceConfig
from app.collector_client.sources.base import SourceResult, stamp_source
from app.collector_client.telemetry_utils import clean, command_category, hash_value, ref
from app.collector_client.tool_execution import command_excerpt, command_text
from app.collector_client.usage_contract import normalized_usage_projection, usage_signal_from_projection

SOURCE_KIND = "claude_local"
_SOURCE_TEMPLATE = "claude.local.sessions.v1"
_EXIT_CODE_RE = re.compile(r"Exit code:\s*([1-9]\d*)")
_ERROR_RE = re.compile(r"^(Error:|Traceback)", re.MULTILINE)
_SKIP_TYPES = {"queue-operation", "queue_operation", "attachment"}


def collect_claude_source(
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
    session_titles = cursor.setdefault("claude_session_titles", {})
    tool_use_cache = cursor.setdefault("claude_tool_use", {})
    seen_message_ids = set(str(k) for k in cursor.setdefault("claude_seen_message_ids", []) if k)
    facts: list[dict] = []
    limit = max(1, max_events)
    records = _records(config.root, cursor, max_events=limit, history_window_days=history_window_days)
    for source_key, path, line, record in records:
        for fact in _fact(collector_id, sequence, source_key, path, line, record, session_titles, tool_use_cache, seen_message_ids):
            facts.append(fact)
            if len(facts) >= limit:
                break
        if len(facts) >= limit:
            break
    cursor["claude_seen_message_ids"] = sorted(seen_message_ids)[-5000:]
    cursor["claude_tool_use"] = dict(list(tool_use_cache.items())[-2000:])
    return SourceResult(config, "online", "collected", stamp_source(facts, config))


def _records(root: Path, cursor: dict, *, max_events: int, history_window_days: int) -> Iterable[tuple[str, Path, int, dict]]:
    emitted = 0
    cutoff = datetime.now(UTC) - timedelta(days=max(1, history_window_days))
    cursor.setdefault("sources", {})
    session_titles = cursor.setdefault("claude_session_titles", {})
    for path in _candidate_files(root, cutoff):
        if emitted >= max_events:
            break
        path_hash = hash_value(path.as_posix())
        file_state = _file_state(cursor, path_hash)
        try:
            stat = path.stat()
        except OSError:
            continue
        if (int(file_state.get("size") or 0) == stat.st_size
                and float(file_state.get("mtime") or 0) == stat.st_mtime
                and int(file_state.get("byte_offset") or 0) >= stat.st_size):
            continue
        byte_offset = int(file_state.get("byte_offset") or 0)
        line_no = int(file_state.get("line_no") or 0)
        if byte_offset == 0:
            _prescan_ai_titles(path, session_titles)
        if stat.st_size < byte_offset:
            byte_offset = 0
            line_no = 0
        for line, offset, payload in _jsonl_records(path, byte_offset, line_no):
            source_key = f"{path.as_posix()}:{line:08d}"
            file_state.update({"path": path.as_posix(), "size": stat.st_size, "mtime": stat.st_mtime, "byte_offset": offset, "line_no": line})
            cursor["sources"][path_hash] = file_state
            yield source_key, path, line, payload
            emitted += 1
            if emitted >= max_events:
                break


def _candidate_files(root: Path, cutoff: datetime) -> list[Path]:
    base = root / "projects"
    if not base.exists():
        return []
    paths: list[tuple[float, Path]] = []
    for project_dir in base.iterdir():
        if not project_dir.is_dir():
            continue
        for path in project_dir.iterdir():
            if not path.is_file() or path.suffix.lower() != ".jsonl":
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if datetime.fromtimestamp(stat.st_mtime, UTC) >= cutoff:
                paths.append((-stat.st_mtime, path))
    paths.sort(key=lambda item: (item[0], item[1].as_posix()))
    return [path for _, path in paths]


def _file_state(cursor: dict, path_hash: str) -> dict:
    sources = cursor.setdefault("sources", {})
    state = sources.get(path_hash) if isinstance(sources, dict) else None
    return state if isinstance(state, dict) else {"size": 0, "mtime": 0.0, "byte_offset": 0, "line_no": 0}


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


def _prescan_ai_titles(path: Path, session_titles: dict) -> None:
    try:
        with path.open("rb") as handle:
            for line in handle:
                try:
                    payload = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and payload.get("type") in {"ai-title", "ai_title"}:
                    title = payload.get("aiTitle") or payload.get("ai_title")
                    if title:
                        session_titles[_session_id(payload, path)] = str(title)
    except OSError:
        return


def _fact(collector_id, sequence, source_key, path, line, record, session_titles, tool_use_cache, seen_message_ids) -> list[dict]:
    event_type = clean(record.get("type") or "")
    if event_type in _SKIP_TYPES:
        return []
    if event_type in {"ai-title", "ai_title"}:
        title = record.get("aiTitle") or record.get("ai_title")
        if title:
            session_titles[_session_id(record, path)] = str(title)
        return []
    if event_type == "user":
        return _user_facts(collector_id, sequence, source_key, path, line, record, session_titles, tool_use_cache)
    if event_type == "assistant":
        return _assistant_facts(collector_id, sequence, source_key, path, line, record, session_titles, tool_use_cache, seen_message_ids)
    return []


def _user_facts(collector_id, sequence, source_key, path, line, record, session_titles, tool_use_cache) -> list[dict]:
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        base = _common(collector_id, sequence, source_key, path, line, record, "user", session_titles)
        text = content.strip()
        return [_content_fact(base, "agent_prompt", "user", text, "记录到 Claude 用户消息，已上传原始内容。")]
    if isinstance(content, list):
        facts: list[dict] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                fact = _tool_result_fact(collector_id, sequence, source_key, path, line, record, item, session_titles, tool_use_cache)
                if fact:
                    facts.append(fact)
        return facts
    return []


def _assistant_facts(collector_id, sequence, source_key, path, line, record, session_titles, tool_use_cache, seen_message_ids) -> list[dict]:
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    content = message.get("content")
    facts: list[dict] = []
    if isinstance(content, list):
        for index, item in enumerate(content):
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                base = _common(collector_id, sequence, source_key, path, line, record, "assistant", session_titles, discriminator=f"text:{index}")
                facts.append(_content_fact(base, "agent_response", "assistant", str(item.get("text") or "").strip(), "记录到 Claude 助手响应，已上传原始内容。"))
            elif item_type == "tool_use":
                fact = _tool_use_fact(collector_id, sequence, source_key, path, line, record, item, session_titles, tool_use_cache)
                if fact:
                    facts.append(fact)
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else None
    if usage:
        message_id = str(message.get("id") or "")
        if not message_id or message_id not in seen_message_ids:
            if message_id:
                seen_message_ids.add(message_id)
            facts.append(_usage_fact(collector_id, sequence, source_key, path, line, record, session_titles, usage, message))
    return facts


def _content_fact(base: dict, category: str, role: str, text: str, summary: str) -> dict:
    return {**base, "fact_type": "content", "category": category, "quality": "high" if text else "low", "severity": "low", "summary": summary, "projection": {"role": role, "content_text": text, "content_length": len(text), "raw_content_uploaded": True}}


def _tool_use_fact(collector_id, sequence, source_key, path, line, record, item, session_titles, tool_use_cache) -> dict:
    tool_name = clean(item.get("name") or "unknown_tool")
    call_id = str(item.get("id") or "")
    base = _common(collector_id, sequence, source_key, path, line, record, "assistant", session_titles, discriminator=call_id)
    if call_id:
        tool_use_cache[call_id] = tool_name
    tool_input = item.get("input") if isinstance(item.get("input"), dict) else {}
    command = command_text(tool_input)
    command_cat = command_category(command)
    projection: dict = {"tool_name": tool_name, "tool_call_id": call_id, "command_category": command_cat, "raw_content_uploaded": True}
    if command:
        projection["command"] = command
        projection["command_excerpt"] = command_excerpt(command)
    else:
        projection["command_excerpt"] = command_excerpt(json.dumps(tool_input, ensure_ascii=False))
    return {**base, "fact_type": "tool", "category": "tool_call", "quality": "high", "severity": "low", "summary": f"Claude 工具调用已采集：{tool_name}。", "projection": projection}


def _tool_result_fact(collector_id, sequence, source_key, path, line, record, item, session_titles, tool_use_cache) -> dict:
    call_id = str(item.get("tool_use_id") or "")
    tool_name = tool_use_cache.get(call_id) or "unknown"
    base = _common(collector_id, sequence, source_key, path, line, record, "user", session_titles, discriminator=call_id)
    raw_output = item.get("content")
    if isinstance(raw_output, list):
        output_text = "\n".join(str(p.get("text") or "") for p in raw_output if isinstance(p, dict))
    elif isinstance(raw_output, str):
        output_text = raw_output
    else:
        output_text = json.dumps(raw_output, ensure_ascii=False) if raw_output else ""
    exit_code = _extract_exit_code(output_text)
    if exit_code is not None or _ERROR_RE.search(output_text):
        signature = f"tool_execution_failure:{tool_name}:tool_result:{exit_code if exit_code is not None else 'none'}"
        return {**base, "fact_type": "error", "category": "tool_execution_failure", "quality": "high", "severity": "high", "summary": f"Claude 工具执行失败（exit={exit_code}）。", "projection": {"tool_name": tool_name, "tool_call_id": call_id, "exit_code": exit_code, "output_excerpt": output_text[:240], "raw_content_uploaded": True}, "error_signature": {"signature_key": signature, "category": "tool_execution_failure", "tool_name": tool_name, "exit_code": exit_code, "object_type": "tool_result"}}
    return {**base, "fact_type": "tool", "category": "tool_result", "quality": "high", "severity": "low", "summary": f"Claude 工具结果已采集：{tool_name}。", "projection": {"tool_name": tool_name, "tool_call_id": call_id, "result_excerpt": output_text[:240], "raw_content_uploaded": True}}


def _usage_fact(collector_id, sequence, source_key, path, line, record, session_titles, usage, message) -> dict:
    message_id = str(message.get("id") or "")
    base = _common(collector_id, sequence, source_key, path, line, record, "assistant", session_titles, discriminator=f"usage:{message_id}")
    projection = normalized_usage_projection(
        activity_tag="claude_turn",
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cached_input_tokens=usage.get("cache_read_input_tokens"),
        cache_write_input_tokens=usage.get("cache_creation_input_tokens"),
        model=str(record.get("model") or message.get("model") or ""),
        provider="anthropic",
    )
    refs = base["source_refs"]
    units = int(projection.get("units") or 0)
    return {**base, "fact_type": "usage", "category": "usage", "quality": "high" if projection.get("observability_level") == "full" else "low", "severity": "medium" if units >= 100 else "low", "summary": "Claude 记录到模型调用用量。", "projection": projection, "usage": usage_signal_from_projection(projection, scope="session", session_id=str(refs.get("session_ref") or "unknown"), conversation_id=str(refs.get("conversation_ref") or "unknown"), project_ref=str(refs.get("workspace_path") or "unknown"), account_ref="local")}


def _common(collector_id, sequence, source_key, path, line, record, event_type, session_titles, *, discriminator: str = "") -> dict:
    session_id = _session_id(record, path)
    raw_content = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    source_path_hash = hash_value(path.as_posix())[:16]
    refs = {
        "collector_id": collector_id,
        "sequence": sequence,
        "source_key": source_key,
        "source_path_hash": source_path_hash,
        "line": line,
        "conversation_ref": ref(session_id),
        "session_ref": ref(session_id),
        "workspace_path": _workspace_path(record, path),
    }
    title = session_titles.get(session_id)
    if title:
        refs["session_title"] = title
    hash_parts: tuple = (source_path_hash, line, event_type, raw_content)
    if discriminator:
        hash_parts = hash_parts + (discriminator,)
    return {
        "source_event_id": f"claude-{hash_value(*hash_parts)[:32]}",
        "fact_type": "unknown",
        "category": "uncategorized",
        "quality": "low",
        "severity": "low",
        "summary": "Claude 事件已采集。",
        "occurred_at": _occurred_at(record),
        "raw_hash": hash_value(raw_content),
        "span": f"claude-session:{hash_value(source_key)[:12]}",
        "source_refs": refs,
        "source_specific": {"event_type": event_type, "source_template": _SOURCE_TEMPLATE},
        "upload_raw": True,
        "raw_content": raw_content,
    }


def _session_id(record: dict, path: Path) -> str:
    return str(record.get("sessionId") or record.get("session_id") or path.stem)


def _workspace_path(record: dict, path: Path) -> str:
    cwd = record.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    return _decode_project_dir(path.parent.name)


def _decode_project_dir(name: str) -> str:
    if not name:
        return ""
    chars = list(name)
    restored = False
    for i, ch in enumerate(chars):
        if ch == "-":
            chars[i] = ":" if not restored else "\\"
            if not restored:
                restored = True
    return "".join(chars)


def _occurred_at(record: dict) -> str:
    raw = record.get("timestamp")
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(raw, (int, float)):
        value = raw / 1000 if raw > 10_000_000_000 else raw
        return datetime.fromtimestamp(value, UTC).replace(microsecond=0).isoformat()
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _extract_exit_code(text: str) -> int | None:
    if not isinstance(text, str):
        return None
    match = _EXIT_CODE_RE.search(text)
    return int(match.group(1)) if match else None


collect = collect_claude_source
