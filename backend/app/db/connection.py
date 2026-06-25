from __future__ import annotations

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
          enrichment_mode text not null,
          collection_interval_seconds integer not null default 5,
          max_events_per_cycle integer not null default 500,
          upload_batch_size integer not null default 100,
          worker_poll_interval_seconds integer not null default 10
        );

        create table if not exists collectors (
          collector_id text primary key,
          display_name text not null,
          hostname_hash text not null,
          windows_username_hash text not null,
          protocol_version text not null default '',
          agent_version text not null,
          source_status text not null,
          reason_code text not null,
          policy_version integer not null,
          last_heartbeat_at text,
          outbox_backlog integer not null default 0,
          runtime_phase text not null default 'idle',
          last_seen_at text,
          last_cycle_duration_ms integer,
          last_error text,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists agent_sources (
          source_id text not null,
          collector_id text not null,
          agent_type text not null,
          source_kind text not null,
          display_name text not null,
          capabilities_json text not null,
          source_status text not null,
          reason_code text not null,
          last_seen_at text,
          created_at text not null,
          updated_at text not null,
          primary key (collector_id, source_id)
        );

        create table if not exists telemetry_batches (
          batch_id text primary key,
          collector_id text not null,
          source_id text not null,
          source text not null,
          agent_type text not null,
          source_kind text not null,
          protocol_version text not null default '',
          agent_version text not null default '',
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
          source_id text not null,
          source text not null,
          agent_type text not null,
          source_kind text not null,
          fact_type text not null,
          category text not null,
          normalized_event_type text not null default '',
          quality text not null,
          severity text not null,
          summary text not null,
          occurred_at text not null,
          promoted_to_signal integer not null default 0,
          source_refs_json text not null,
          source_specific_json text not null,
          content_preview text not null default '',
          raw_available integer not null default 0,
          raw_status text not null default '仅结构化字段',
          conversation_ref text not null default '',
          session_ref text not null default '',
          source_event_type text not null default '',
          source_path_hash text not null default '',
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

        create table if not exists error_signature_facts (
          signature_key text not null,
          fact_id text not null,
          category text not null,
          occurred_at text not null,
          primary key (signature_key, fact_id)
        );

        create table if not exists usage_signals (
          signal_id text primary key,
          fact_id text not null,
          scope text not null,
          units integer not null,
          activity_tag text not null,
          session_id text not null default 'unknown',
          conversation_id text not null default 'unknown',
          project_ref text not null default 'unknown',
          account_ref text not null default 'unknown',
          input_tokens integer not null default 0,
          output_tokens integer not null default 0,
          total_tokens integer not null default 0,
          cached_input_tokens integer not null default 0,
          cache_write_input_tokens integer not null default 0,
          reasoning_output_tokens integer not null default 0,
          model text not null default '',
          provider text not null default '',
          credit real not null default 0,
          unit_basis text not null default 'non_cached_input_plus_output',
          observability_level text not null default 'total_only',
          cache_observed integer not null default 0
        );

        create table if not exists usage_rollups (
          rollup_id text primary key,
          window text not null,
          scope text not null,
          scope_value text not null,
          units integer not null,
          activity_tag text not null,
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

        create table if not exists behavior_signals (
          signal_id text primary key,
          signal_key text not null unique,
          signal_kind text not null,
          title text not null,
          why_it_matters text not null,
          severity text not null,
          confidence text not null,
          priority_score integer not null,
          affected_scope_json text not null,
          evidence_groups_json text not null,
          linked_conversations_json text not null,
          usage_summary_json text not null,
          enrichment_status_summary_json text not null,
          suggested_actions_json text not null,
          decision_state text not null,
          snapshot_hash text not null,
          first_seen_at text not null,
          last_seen_at text not null,
          last_event_at text not null,
          occurrence_count integer not null,
          latest_fact_id text,
          latest_summary text not null,
          updated_at text not null
        );

        create table if not exists processing_jobs (
          job_id text primary key,
          job_type text not null,
          scope_type text not null,
          scope_id text not null,
          status text not null,
          priority integer not null default 50,
          attempts integer not null default 0,
          last_error text not null default '',
          created_at text not null,
          updated_at text not null,
          started_at text,
          finished_at text
        );

        create table if not exists signal_decisions (
          signal_id text primary key,
          decision_state text not null,
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

        create table if not exists enrichment_jobs (
          job_id text primary key,
          signal_id text not null,
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

        create table if not exists enrichment_results (
          result_id text primary key,
          job_id text not null unique,
          signal_id text not null,
          capability_id text not null,
          output_schema text not null,
          status text not null,
          summary text not null,
          projection_json text not null,
          redaction_json text not null,
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
    _ensure_effective_policy_columns(conn)
    _ensure_usage_signal_columns(conn)
    _seed_effective_policy(conn)
    _ensure_indexes(conn)
    conn.commit()


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def _seed_effective_policy(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        insert or ignore into effective_policies
          (id, policy_version, enrichment_mode, collection_interval_seconds, max_events_per_cycle, upload_batch_size, worker_poll_interval_seconds)
        values (1, 1, 'enabled', 5, 500, 100, 10)
        """
    )


def _ensure_effective_policy_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("pragma table_info(effective_policies)").fetchall()}
    if "collection_interval_seconds" not in columns:
        conn.execute("alter table effective_policies add column collection_interval_seconds integer not null default 5")
    if "max_events_per_cycle" not in columns:
        conn.execute("alter table effective_policies add column max_events_per_cycle integer not null default 500")
    if "upload_batch_size" not in columns:
        conn.execute("alter table effective_policies add column upload_batch_size integer not null default 100")
    if "worker_poll_interval_seconds" not in columns:
        conn.execute("alter table effective_policies add column worker_poll_interval_seconds integer not null default 10")


def _ensure_usage_signal_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("pragma table_info(usage_signals)").fetchall()}
    definitions = {
        "input_tokens": "integer not null default 0",
        "output_tokens": "integer not null default 0",
        "total_tokens": "integer not null default 0",
        "cached_input_tokens": "integer not null default 0",
        "cache_write_input_tokens": "integer not null default 0",
        "reasoning_output_tokens": "integer not null default 0",
        "model": "text not null default ''",
        "provider": "text not null default ''",
        "credit": "real not null default 0",
        "unit_basis": "text not null default 'non_cached_input_plus_output'",
        "observability_level": "text not null default 'total_only'",
        "cache_observed": "integer not null default 0",
    }
    for column, definition in definitions.items():
        if column not in columns:
            conn.execute(f"alter table usage_signals add column {column} {definition}")


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create unique index if not exists idx_observed_facts_collector_source_event
          on observed_facts(collector_id, source_id, source_event_id);
        create index if not exists idx_agent_sources_collector
          on agent_sources(collector_id, source_status);
        create index if not exists idx_observed_facts_occurred_at
          on observed_facts(occurred_at desc);
        create index if not exists idx_observed_facts_created_at
          on observed_facts(created_at desc);
        create index if not exists idx_observed_facts_conversation_occurred
          on observed_facts(conversation_ref, occurred_at desc);
        create index if not exists idx_observed_facts_effective_conversation_path_occurred
          on observed_facts(
            coalesce(nullif(conversation_ref, ''), nullif(session_ref, ''), fact_id),
            source_path_hash,
            occurred_at
          );
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
        create index if not exists idx_observed_facts_agent_occurred_at
          on observed_facts(agent_type, occurred_at desc);
        create index if not exists idx_observed_facts_source_id_occurred_at
          on observed_facts(source_id, occurred_at desc);
        create index if not exists idx_observed_facts_category_occurred_at
          on observed_facts(category, occurred_at desc);
        create index if not exists idx_error_signatures_category_key
          on error_signatures(category, signature_key);
        create index if not exists idx_error_signature_facts_fact_id
          on error_signature_facts(fact_id);
        create index if not exists idx_error_signature_facts_category_key
          on error_signature_facts(category, signature_key);
        create index if not exists idx_evidence_projections_fact_id
          on evidence_projections(fact_id);
        create index if not exists idx_usage_signals_conversation_id
          on usage_signals(conversation_id);
        create index if not exists idx_behavior_signals_decision_last_event
          on behavior_signals(decision_state, last_event_at desc);
        create index if not exists idx_behavior_signals_kind_last_event
          on behavior_signals(signal_kind, last_event_at desc);
        create index if not exists idx_processing_jobs_status_priority_updated
          on processing_jobs(status, priority desc, updated_at);
        create index if not exists idx_processing_jobs_type_scope
          on processing_jobs(job_type, scope_type, scope_id);
        """
    )


