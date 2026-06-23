from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.collector_client.content_dedup import add_or_merge_content_fact
from app.collector_client.fact_mapper import _record_fact
from app.collector_client.session_index import load_session_titles
from app.collector_client.source_reader import _incremental_records, _recent_tail_records
from app.collector_client.telemetry_utils import codex_home as _codex_home
from app.collector_client.workspace_scope import load_workspace_resolver


def collect_facts(
    collector_id: str,
    sequence: int,
    telemetry_mode: str,
    *,
    codex_home: str | Path | None = None,
    history_window_days: int = 7,
    max_events: int = 500,
    cursor: dict | None = None,
) -> list[dict]:
    root = _codex_home(codex_home)
    sessions_dir = root / "sessions"
    if not sessions_dir.exists():
        return []
    return _codex_facts(
        collector_id=collector_id,
        sequence=sequence,
        codex_home=root,
        history_window_days=history_window_days,
        max_events=max_events,
        cursor={} if cursor is None else cursor,
    )

def _codex_facts(
    *,
    collector_id: str,
    sequence: int,
    codex_home: Path,
    history_window_days: int,
    max_events: int,
    cursor: dict,
) -> list[dict]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=max(1, history_window_days))
    cursor.setdefault("sources", {})
    session_titles = load_session_titles(codex_home)
    workspace_resolver = load_workspace_resolver(codex_home)
    facts: list[dict] = []
    content_index: dict[str, int] = {}
    seen_source_keys: set[str] = set()
    live_seen = set(str(item) for item in cursor.get("live_tail_source_keys", []))
    if cursor.get("sources"):
        for source_key, path, line_number, record in _recent_tail_records(
            sessions_dir,
            cutoff,
            cursor=cursor,
            max_records=max(1, max_events),
        ):
            if source_key in live_seen or source_key in seen_source_keys:
                continue
            fact = _record_fact(
                collector_id,
                sequence,
                source_key,
                path,
                line_number,
                record,
                session_titles=session_titles,
                workspace_resolver=workspace_resolver,
            )
            if fact:
                fact["source_specific"]["priority_stream"] = "live_tail"
                add_or_merge_content_fact(facts, content_index, fact)
                seen_source_keys.add(source_key)
                live_seen.add(source_key)
            if len(facts) >= max(1, max_events):
                cursor["live_tail_source_keys"] = sorted(live_seen)[-1000:]
                return facts
        cursor["live_tail_source_keys"] = sorted(live_seen)[-1000:]
    for source_key, path, line_number, record in _incremental_records(sessions_dir, cutoff, cursor, max(1, max_events)):
        if len(facts) >= max(1, max_events):
            break
        if source_key in seen_source_keys:
            continue
        fact = _record_fact(
            collector_id,
            sequence,
            source_key,
            path,
            line_number,
            record,
            session_titles=session_titles,
            workspace_resolver=workspace_resolver,
        )
        if fact:
            fact["source_specific"]["priority_stream"] = "file_cursor"
            add_or_merge_content_fact(facts, content_index, fact)
            seen_source_keys.add(source_key)
    return facts
