from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from app.collector_client.command_context import attach_call_context
from app.collector_client.workspace_scope import workspace_hint_from_file
from app.collector_client.telemetry_utils import (
    hash_value as _hash,
    occurred_at as _occurred_at,
    payload as _payload,
    stable_projection as _stable_projection,
)


def _incremental_records(sessions_dir: Path, cutoff: datetime, cursor: dict, limit: int) -> Iterable[tuple[str, Path, int, dict]]:
    emitted = 0
    for _, path, stat in _candidate_files(sessions_dir, cutoff):
        if emitted >= limit:
            break
        workspace_hint = workspace_hint_from_file(path)
        path_hash = _hash(path.as_posix())
        sources = cursor.setdefault("sources", {})
        file_state = sources.get(path_hash) if isinstance(sources, dict) else None
        if not isinstance(file_state, dict):
            file_state = {
                "path": path.as_posix(),
                "path_hash": path_hash,
                "size": 0,
                "mtime": 0.0,
                "byte_offset": 0,
                "line_no": 0,
                "last_event_ts": None,
                "last_event_hash": None,
            }
        if _fully_consumed(file_state, stat):
            continue
        if stat.st_size < int(file_state.get("size") or 0):
            file_state["byte_offset"] = 0
            file_state["line_no"] = 0
        for source_key, line_number, byte_offset, record in _file_records_from_offset(
            path,
            int(file_state.get("byte_offset") or 0),
            int(file_state.get("line_no") or 0),
            cursor,
            max_records=max(1, limit - emitted),
        ):
            yield source_key, path, line_number, _attach_workspace_hint(record, workspace_hint)
            emitted += 1
            file_state.update(
                {
                    "path": path.as_posix(),
                    "path_hash": path_hash,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "byte_offset": byte_offset,
                    "line_no": line_number,
                    "last_event_ts": _occurred_at(record),
                    "last_event_hash": _hash(_stable_projection(record, include_values=True)),
                }
            )
            sources[path_hash] = file_state
            if emitted >= limit:
                break
        else:
            file_state.update({"path": path.as_posix(), "path_hash": path_hash, "size": stat.st_size, "mtime": stat.st_mtime})
            sources[path_hash] = file_state

def _candidate_files(sessions_dir: Path, cutoff: datetime) -> list[tuple[float, Path, object]]:
    paths = []
    for path in sessions_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".jsonl", ".json", ".ndjson"}:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if datetime.fromtimestamp(stat.st_mtime, UTC) >= cutoff:
            paths.append((stat.st_mtime, path, stat))
    paths.sort(key=lambda item: (item[0], item[1].as_posix()), reverse=True)
    return paths

def _fully_consumed(file_state: dict, stat: object) -> bool:
    current_size = int(getattr(stat, "st_size", 0) or 0)
    same_file_version = (
        int(file_state.get("size") or 0) == current_size
        and float(file_state.get("mtime") or 0) == float(getattr(stat, "st_mtime", 0) or 0)
    )
    return same_file_version and int(file_state.get("byte_offset") or 0) >= current_size

def _file_records_from_offset(
    path: Path,
    byte_offset: int,
    line_no: int,
    cursor: dict | None = None,
    *,
    max_records: int | None = None,
) -> Iterable[tuple[str, int, int, dict]]:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, byte_offset))
            records = []
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
                    records.append((current_line, offset, payload))
                    if max_records is not None and len(records) >= max(1, max_records):
                        break
    except OSError:
        return
    for record_line, offset, record in _attach_context_with_offsets(records, cursor or {}):
        source_key = f"{path.as_posix()}:{record_line:08d}"
        yield source_key, record_line, offset, record

def _attach_context_with_offsets(records: list[tuple[int, int, dict]], cursor: dict) -> list[tuple[int, int, dict]]:
    seed_rows = _stored_call_context_rows(cursor)
    contextual = attach_call_context([*seed_rows, *[(line_no, record) for line_no, _, record in records]])
    offsets = {line_no: offset for line_no, offset, _ in records}
    _remember_call_context(cursor, records)
    return [(line_no, offsets[line_no], record) for line_no, record in contextual if line_no in offsets]

def _stored_call_context_rows(cursor: dict) -> list[tuple[int, dict]]:
    context = cursor.get("call_context")
    if not isinstance(context, dict):
        return []
    rows = []
    for index, item in enumerate(context.values(), 1):
        if isinstance(item, dict) and isinstance(item.get("record"), dict):
            rows.append((-index, item["record"]))
    return rows

def _remember_call_context(cursor: dict, records: list[tuple[int, int, dict]]) -> None:
    context = cursor.setdefault("call_context", {})
    if not isinstance(context, dict):
        context = {}
        cursor["call_context"] = context
    for line_no, _, record in records:
        payload = _payload(record)
        if payload.get("type") != "function_call":
            continue
        call_id = str(payload.get("call_id") or "")
        if call_id:
            context[call_id] = {"line": line_no, "record": record}
    if len(context) > 500:
        for key in list(context.keys())[:-500]:
            context.pop(key, None)

def _recent_tail_records(
    sessions_dir: Path,
    cutoff: datetime,
    cursor: dict | None = None,
    max_records: int = 250,
) -> Iterable[tuple[str, Path, int, dict]]:
    live_cutoff = datetime.now(UTC) - timedelta(minutes=30)
    for _, path, stat in _candidate_files(sessions_dir, max(cutoff, live_cutoff))[:5]:
        if cursor is not None and not _should_tail_v2_file(cursor, path, stat):
            continue
        min_line = _v2_tail_min_line(cursor, path) if cursor is not None else 0
        workspace_hint = workspace_hint_from_file(path)
        records = [(line_no, record) for line_no, record in _tail_records(path, max_records=max(1, max_records)) if line_no > min_line]
        contextual = attach_call_context([*_stored_call_context_rows(cursor or {}), *records])
        _remember_call_context(cursor or {}, [(line_no, 0, record) for line_no, record in records])
        tail_lines = {line_no for line_no, _ in records}
        for line_number, record in reversed(contextual):
            if line_number not in tail_lines:
                continue
            source_key = f"{path.as_posix()}:{line_number:08d}"
            yield source_key, path, line_number, _attach_workspace_hint(record, workspace_hint)

def _should_tail_v2_file(cursor: dict, path: Path, stat: object) -> bool:
    sources = cursor.get("sources")
    if not isinstance(sources, dict):
        return False
    file_state = sources.get(_hash(path.as_posix()))
    if not isinstance(file_state, dict):
        return False
    byte_offset = int(file_state.get("byte_offset") or 0)
    return byte_offset > 0 and byte_offset < int(getattr(stat, "st_size", 0) or 0)

def _v2_tail_min_line(cursor: dict, path: Path) -> int:
    sources = cursor.get("sources")
    if not isinstance(sources, dict):
        return 0
    file_state = sources.get(_hash(path.as_posix()))
    if not isinstance(file_state, dict):
        return 0
    return int(file_state.get("line_no") or 0)

def _tail_records(path: Path, max_records: int, max_bytes: int = 2 * 1024 * 1024) -> list[tuple[int, dict]]:
    try:
        stat = path.stat()
        size = int(stat.st_size)
        start = max(0, size - max_bytes)
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read()
    except OSError:
        return []
    if start > 0:
        newline = data.find(b"\n")
        if newline < 0:
            return []
        start += newline + 1
        data = data[newline + 1 :]
    base_line = _count_newlines_before(path, start)
    lines = data.splitlines()
    if len(lines) > max_records:
        base_line += len(lines) - max_records
        lines = lines[-max_records:]
    records = []
    for index, line in enumerate(lines, 1):
        try:
            payload = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append((base_line + index, payload))
    return records

def _count_newlines_before(path: Path, byte_offset: int) -> int:
    if byte_offset <= 0:
        return 0
    remaining = byte_offset
    count = 0
    try:
        with path.open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                count += chunk.count(b"\n")
                remaining -= len(chunk)
    except OSError:
        return 0
    return count


def _attach_workspace_hint(record: dict, workspace_hint: dict) -> dict:
    if not workspace_hint or _payload(record).get("type") == "session_meta":
        return record
    enriched = dict(record)
    enriched["_workspace_hint"] = workspace_hint
    return enriched

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
