from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path


SOURCE_STATUSES = (
    "online",
    "degraded",
    "offline",
    "source_missing",
    "source_locked",
)

_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[str] = set()

SCHEMA_SQL = """
        create table if not exists effective_policies (
          id integer primary key check (id = 1),
          policy_version integer not null,
          template_enabled integer not null,
          upload_raw integer not null,
          collection_policy text not null,
          diagnostic_policy text not null
        );

        create table if not exists collectors (
          collector_id text primary key,
          display_name text not null,
          hostname_hash text not null,
          windows_username_hash text not null,
          agent_type text not null,
          agent_version text not null,
          source_status text not null,
          reason_code text not null,
          policy_version integer not null,
          last_heartbeat_at text,
          outbox_backlog integer not null default 0,
          raw_upload_enabled integer,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists telemetry_batches (
          batch_id text primary key,
          collector_id text not null,
          source text not null,
          cursor text not null,
          accepted_count integer not null,
          duplicate_count integer not null,
          created_at text not null
        );

        create table if not exists observed_facts (
          fact_id text primary key,
          source_event_id text not null default '',
          batch_id text not null,
          collector_id text not null,
          source text not null,
          fact_type text not null,
          category text not null,
          quality text not null,
          severity text not null,
          summary text not null,
          occurred_at text not null,
          promoted_to_story integer not null default 0,
          source_refs_json text not null,
          source_specific_json text not null,
          created_at text not null
        );

        create table if not exists evidence_projections (
          projection_id text primary key,
          fact_id text not null,
          category text not null,
          span text not null,
          raw_hash text not null,
          projection_json text not null,
          upload_raw integer not null default 0,
          raw_content text
        );

        create table if not exists error_signatures (
          signature_key text primary key,
          fact_id text not null,
          category text not null,
          first_seen_at text not null,
          last_seen_at text not null,
          occurrences integer not null
        );

        create table if not exists usage_signals (
          signal_id text primary key,
          fact_id text not null,
          scope text not null,
          units integer not null,
          activity_tag text not null,
          usage_kind text not null default 'associated',
          session_id text not null default 'unknown',
          conversation_id text not null default 'unknown',
          project_ref text not null default 'unknown',
          account_ref text not null default 'unknown'
        );

        create table if not exists usage_rollups (
          rollup_id text primary key,
          window text not null,
          scope text not null,
          scope_value text not null,
          units integer not null,
          usage_kind text not null,
          activity_tag text not null,
          additive integer not null,
          evidence_refs_json text not null,
          built_at text not null
        );

        create table if not exists risk_signals (
          signal_id text primary key,
          fact_id text not null,
          risk_type text not null,
          severity text not null,
          object_type text not null default 'unknown'
        );

        create table if not exists observation_stories (
          story_id text primary key,
          story_key text not null unique,
          priority_score integer not null,
          evidence_refs_json text not null,
          usage_summary_json text not null,
          diagnostic_status_summary_json text not null,
          attention_state text not null,
          current_snapshot_json text not null,
          snapshot_hash text not null,
          conclusion text not null,
          impact_objects_json text not null,
          suggested_action text not null,
          updated_at text not null
        );

        create table if not exists story_handling_states (
          story_id text primary key,
          handling_state text not null,
          conclusion_code text,
          note text,
          updated_by text not null,
          updated_at text not null
        );

        create table if not exists audit_logs (
          audit_id text primary key,
          object_type text not null,
          object_id text not null,
          action text not null,
          actor text not null,
          metadata_json text not null,
          created_at text not null
        );

        create table if not exists diagnostic_jobs (
          job_id text primary key,
          story_id text not null,
          collector_id text,
          capability_id text not null,
          status text not null,
          command_json text not null,
          reason_code text,
          requested_by text not null,
          requested_at text not null,
          expires_at text not null,
          updated_at text not null
        );

        create table if not exists diagnostic_results (
          result_id text primary key,
          job_id text not null unique,
          story_id text not null,
          status text not null,
          summary text not null,
          projection_json text not null,
          created_at text not null
        );

"""


def default_db_path() -> Path:
    return Path(os.environ.get("AGENT_OBSERVER_DB", "data/agent-observer.sqlite"))


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma busy_timeout = 30000")
    conn.execute("pragma foreign_keys = on")
    resolved = str(path.resolve())
    if resolved not in _INITIALIZED_PATHS:
        with _INIT_LOCK:
            if resolved not in _INITIALIZED_PATHS:
                conn.execute("pragma journal_mode = wal")
                initialize(conn)
                _INITIALIZED_PATHS.add(resolved)
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    _create_tables(conn)
    _seed_effective_policy(conn)
    _migrate_columns(conn)
    _backfill_fact_reference_fields(conn)
    _backfill_fact_list_fields(conn)
    _normalize_legacy_collector_status(conn)
    _backfill_story_metadata(conn)
    _ensure_indexes(conn)
    conn.commit()


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def _seed_effective_policy(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        insert or ignore into effective_policies
          (id, policy_version, template_enabled, upload_raw, collection_policy, diagnostic_policy)
        values (1, 1, 1, 0, 'codex default local observation', 'whitelist only')
        """
    )


def _migrate_columns(conn: sqlite3.Connection) -> None:
    migrations = [
        ("usage_signals", "usage_kind", "text not null default 'associated'"),
        ("usage_signals", "session_id", "text not null default 'unknown'"),
        ("usage_signals", "conversation_id", "text not null default 'unknown'"),
        ("usage_signals", "project_ref", "text not null default 'unknown'"),
        ("usage_signals", "account_ref", "text not null default 'unknown'"),
        ("risk_signals", "object_type", "text not null default 'unknown'"),
        ("diagnostic_jobs", "collector_id", "text"),
        ("observed_facts", "source_event_id", "text not null default ''"),
        ("observed_facts", "content_preview", "text not null default ''"),
        ("observed_facts", "raw_available", "integer not null default 0"),
        ("observed_facts", "raw_status", "text not null default '未上传原文，可查看结构化摘要'"),
        ("observed_facts", "conversation_ref", "text not null default ''"),
        ("observed_facts", "session_ref", "text not null default ''"),
        ("observed_facts", "source_event_type", "text not null default ''"),
        ("observed_facts", "source_path_hash", "text not null default ''"),
        ("collectors", "raw_upload_enabled", "integer"),
        ("collectors", "runtime_phase", "text not null default 'idle'"),
        ("collectors", "last_seen_at", "text"),
        ("collectors", "last_cycle_duration_ms", "integer"),
        ("collectors", "last_error", "text"),
        ("evidence_projections", "raw_content", "text"),
        ("observation_stories", "story_type", "text not null default 'unknown'"),
        ("observation_stories", "first_seen_at", "text"),
        ("observation_stories", "last_seen_at", "text"),
        ("observation_stories", "last_event_at", "text"),
        ("observation_stories", "occurrence_count", "integer not null default 0"),
        ("observation_stories", "primary_object_type", "text"),
        ("observation_stories", "primary_object_value", "text"),
        ("observation_stories", "latest_fact_id", "text"),
        ("observation_stories", "latest_summary", "text"),
    ]
    for table, column, definition in migrations:
        _ensure_column(conn, table, column, definition)


def _normalize_legacy_collector_status(conn: sqlite3.Connection) -> None:
    conn.execute("update collectors set source_status = 'degraded', reason_code = 'policy_stale' where source_status = 'policy_not_fetched'")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")


def _backfill_fact_list_fields(conn: sqlite3.Connection) -> None:
    from app.evidence.presentation import projection_preview, raw_available, raw_status_label

    rows = conn.execute(
        """
        select f.fact_id, f.summary,
               p.category as projection_category, p.projection_json, p.upload_raw, p.raw_content
        from observed_facts f
        left join evidence_projections p on p.projection_id = (
          select projection_id from evidence_projections
          where fact_id = f.fact_id
          order by projection_id
          limit 1
        )
        where f.content_preview = ''
           or f.raw_status = '未上传原文，可查看结构化摘要'
        """
    ).fetchall()
    for row in rows:
        projection = _loads(row["projection_json"]) if row["projection_json"] else {}
        upload_raw = bool(row["upload_raw"]) if row["upload_raw"] is not None else False
        raw_content = row["raw_content"]
        if row["projection_json"]:
            preview = projection_preview(projection, raw_content, row["summary"], row["projection_category"] or "")
            raw_state = raw_status_label(upload_raw, raw_content)
            raw_flag = raw_available(upload_raw, raw_content)
        else:
            preview = row["summary"]
            raw_state = "无证据投影"
            raw_flag = False
        conn.execute(
            """
            update observed_facts
            set content_preview = ?, raw_available = ?, raw_status = ?
            where fact_id = ?
            """,
            (preview, 1 if raw_flag else 0, raw_state, row["fact_id"]),
        )


def _backfill_fact_reference_fields(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        select fact_id, source_refs_json, source_specific_json
        from observed_facts
        where conversation_ref = ''
           or session_ref = ''
           or source_event_type = ''
           or source_path_hash = ''
        """
    ).fetchall()
    for row in rows:
        refs = _loads(row["source_refs_json"])
        specific = _loads(row["source_specific_json"])
        conn.execute(
            """
            update observed_facts
            set conversation_ref = ?,
                session_ref = ?,
                source_event_type = ?,
                source_path_hash = ?
            where fact_id = ?
            """,
            (
                str(refs.get("conversation_ref") or ""),
                str(refs.get("session_ref") or ""),
                str(specific.get("codex_event_type") or ""),
                str(refs.get("source_path_hash") or ""),
                row["fact_id"],
            ),
        )


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create unique index if not exists idx_observed_facts_collector_source_event
          on observed_facts(collector_id, source_event_id);
        create index if not exists idx_observed_facts_occurred_at
          on observed_facts(occurred_at desc);
        create index if not exists idx_observed_facts_created_at
          on observed_facts(created_at desc);
        create index if not exists idx_observed_facts_conversation_occurred
          on observed_facts(conversation_ref, occurred_at desc);
        create index if not exists idx_observed_facts_fact_type_occurred_at
          on observed_facts(fact_type, occurred_at desc);
        create index if not exists idx_observed_facts_fact_type_created_at
          on observed_facts(fact_type, created_at desc);
        create index if not exists idx_observed_facts_quality_occurred_at
          on observed_facts(quality, occurred_at desc);
        create index if not exists idx_observed_facts_quality_created_at
          on observed_facts(quality, created_at desc);
        create index if not exists idx_observed_facts_source_occurred_at
          on observed_facts(source, occurred_at desc);
        create index if not exists idx_observed_facts_source_created_at
          on observed_facts(source, created_at desc);
        create index if not exists idx_observed_facts_category_occurred_at
          on observed_facts(category, occurred_at desc);
        create index if not exists idx_error_signatures_category_key
          on error_signatures(category, signature_key);
        create index if not exists idx_evidence_projections_fact_id
          on evidence_projections(fact_id);
        create index if not exists idx_observation_stories_attention_last_event
          on observation_stories(attention_state, last_event_at desc);
        create index if not exists idx_observation_stories_type_last_event
          on observation_stories(story_type, last_event_at desc);
        """
    )


def _backfill_story_metadata(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        select story_id, story_key, evidence_refs_json, current_snapshot_json,
               impact_objects_json, conclusion, updated_at
        from observation_stories
        where last_event_at is null
           or story_type = 'unknown'
           or occurrence_count = 0
        """
    ).fetchall()
    for row in rows:
        snapshot = _loads(row["current_snapshot_json"])
        evidence_chain = snapshot.get("evidence_chain") if isinstance(snapshot.get("evidence_chain"), list) else []
        latest = _latest_evidence(evidence_chain)
        impact_objects = _loads_list(row["impact_objects_json"])
        story_type = str(row["story_key"]).split(":", 1)[0] if ":" in str(row["story_key"]) else "unknown"
        conn.execute(
            """
            update observation_stories
            set story_type = ?,
                first_seen_at = coalesce(first_seen_at, ?),
                last_seen_at = coalesce(last_seen_at, ?),
                last_event_at = coalesce(last_event_at, ?),
                occurrence_count = case when occurrence_count > 0 then occurrence_count else ? end,
                primary_object_type = coalesce(primary_object_type, ?),
                primary_object_value = coalesce(primary_object_value, ?),
                latest_fact_id = coalesce(latest_fact_id, ?),
                latest_summary = coalesce(latest_summary, ?)
            where story_id = ?
            """,
            (
                story_type,
                latest["occurred_at"] or row["updated_at"],
                latest["occurred_at"] or row["updated_at"],
                latest["occurred_at"] or row["updated_at"],
                max(1, len(set(_loads_list(row["evidence_refs_json"])))),
                story_type,
                impact_objects[0] if impact_objects else story_type,
                latest["fact_id"],
                latest["summary"] or row["conclusion"],
                row["story_id"],
            ),
        )


def _latest_evidence(entries: list[object]) -> dict:
    latest = {"occurred_at": None, "fact_id": None, "summary": ""}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        occurred_at = entry.get("occurred_at")
        if not occurred_at:
            continue
        if latest["occurred_at"] is None or str(occurred_at) > str(latest["occurred_at"]):
            latest = {
                "occurred_at": str(occurred_at),
                "fact_id": entry.get("fact_id"),
                "summary": str(entry.get("summary") or ""),
            }
    return latest


def _loads(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_list(value: str | None) -> list:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
