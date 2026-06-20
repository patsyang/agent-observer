from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.collector_client.content_dedup import add_or_merge_content_fact
from app.collector_client.fact_mapper import _health_fact, _record_fact, _source_gap_fact
from app.collector_client.source_reader import _incremental_records, _recent_tail_records
from app.collector_client.telemetry_utils import codex_home as _codex_home, now as _now


def collect_facts(
    collector_id: str,
    sequence: int,
    telemetry_mode: str,
    *,
    codex_home: str | Path | None = None,
    history_window_days: int = 7,
    max_events: int = 500,
    cursor: dict | None = None,
    upload_raw: bool = False,
) -> list[dict]:
    observed_at = _now()
    root = _codex_home(codex_home)
    sessions_dir = root / "sessions"
    facts = [_health_fact(collector_id, sequence, observed_at, telemetry_mode, sessions_dir.exists(), upload_raw)]
    source_facts = _codex_facts(
        collector_id=collector_id,
        sequence=sequence,
        codex_home=root,
        history_window_days=history_window_days,
        max_events=max_events,
        cursor=cursor or {},
        upload_raw=upload_raw,
    )
    if source_facts:
        return facts + source_facts
    return facts + [_source_gap_fact(collector_id, sequence, observed_at, telemetry_mode, sessions_dir.exists(), upload_raw)]

def _codex_facts(
    *,
    collector_id: str,
    sequence: int,
    codex_home: Path,
    history_window_days: int,
    max_events: int,
    cursor: dict,
    upload_raw: bool,
) -> list[dict]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=max(1, history_window_days))
    legacy_last_source_key = str(cursor.get("last_source_key", ""))
    legacy_recent_seen = set(str(item) for item in cursor.get("recent_source_keys", []))
    legacy_mode = not cursor.get("sources") and bool(legacy_last_source_key or legacy_recent_seen)
    cursor.setdefault("sources", {})
    facts: list[dict] = []
    content_index: dict[str, int] = {}
    seen_source_keys: set[str] = set()
    live_seen = set(str(item) for item in cursor.get("live_tail_source_keys", []))
    if legacy_mode or cursor.get("sources"):
        for source_key, path, line_number, record in _recent_tail_records(
            sessions_dir,
            cutoff,
            cursor=None if legacy_mode else cursor,
            max_records=max(1, max_events),
        ):
            if source_key in legacy_recent_seen or source_key in live_seen or source_key in seen_source_keys:
                continue
            fact = _record_fact(collector_id, sequence, source_key, path, line_number, record, upload_raw)
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
        if source_key in seen_source_keys or source_key in legacy_recent_seen or (legacy_last_source_key and source_key <= legacy_last_source_key):
            continue
        fact = _record_fact(collector_id, sequence, source_key, path, line_number, record, upload_raw)
        if fact:
            fact["source_specific"]["priority_stream"] = "file_cursor"
            add_or_merge_content_fact(facts, content_index, fact)
            seen_source_keys.add(source_key)
    return facts
