from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
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
          collection_interval_seconds integer not null default 10,
          max_events_per_cycle integer not null default 500,
          upload_batch_size integer not null default 100,
          worker_poll_interval_seconds integer not null default 10,
          outbox_soft_limit integer not null default 5000,
          log_level text not null default 'INFO'
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

        -- 会话物化层（写时维护，查询只读这一层；列名对齐 API 字段，零映射）
        create table if not exists conversations (
          conversation_ref text primary key,
          base_ref text not null,
          source_path_hash text not null default '',
          session_ref text not null default '',
          session_title text not null default '',
          agent_type text not null default '',
          source_id text not null default '',
          source_kind text not null default '',
          ws_agent_type text not null default '',
          ws_workspace_id text not null default '',
          ws_workspace_path text not null default '',
          ws_workspace_label text not null default '',
          ws_workspace_alias_source text not null default '',
          ws_workspace_confidence text not null default 'unknown',
          started_at text not null,
          last_event_at text not null,
          first_prompt_at text,
          first_response_at text,
          prompt_preview text not null default '',
          response_preview text not null default '',
          prompt_count integer not null default 0,
          response_count integer not null default 0,
          event_count integer not null default 0,
          hit_count integer not null default 0,
          effective_units integer not null default 0,
          model_call_count integer not null default 0,
          max_single_call_units integer not null default 0,
          cached_input_units integer not null default 0,
          input_token_units integer not null default 0,
          output_token_units integer not null default 0,
          total_token_units integer not null default 0,
          cache_write_input_units integer not null default 0,
          reasoning_output_units integer not null default 0,
          credit_total real not null default 0,
          cache_observed_input_units integer not null default 0,
          cache_hit_rate real not null default 0
        );

        create table if not exists conversation_messages (
          fact_id text primary key,
          conversation_ref text not null references conversations(conversation_ref) on delete cascade,
          base_ref text not null,
          source_path_hash text not null default '',
          source_line integer,
          role text not null check (role in ('user','assistant')),
          category text not null,
          occurred_at text not null,
          content text not null,
          raw_available integer not null default 0,
          sensitive_matches_json text not null default '[]'
        );

        create table if not exists conversation_hits (
          fact_id text primary key,
          conversation_ref text not null references conversations(conversation_ref) on delete cascade,
          base_ref text not null default '',
          source_path_hash text not null default '',
          source_line integer,
          category text not null,
          fact_type text not null,
          severity text not null,
          occurred_at text not null,
          summary text not null,
          content_preview text not null,
          tool_context_json text,
          sensitive_matches_json text not null default '[]'
        );

        -- 性能信号：每条调用（LLM/工具/任务/MCP）一行明细，对标 usage_signals
        create table if not exists perf_signals (
          signal_id text primary key,
          fact_id text not null,
          trace_id text not null default '',
          parent_span_id text not null default '',
          span_id text not null default '',
          span_type text not null,
          span_name text not null default '',
          duration_ms integer not null default 0,
          ttft_ms integer not null default 0,
          tps real not null default 0,
          status text not null default 'unknown',
          error text not null default '',
          model text not null default '',
          tool_name text not null default '',
          agent_type text not null default '',
          conversation_ref text not null default '',
          session_ref text not null default '',
          project_ref text not null default '',
          occurred_at text not null,
          foreign key (fact_id) references observed_facts(fact_id)
        );

        -- 性能预聚合：按 window/scope 预聚合百分位，对标 usage_rollups
        create table if not exists perf_rollups (
          rollup_id text primary key,
          window text not null,
          scope text not null,
          scope_value text not null,
          span_type text not null,
          sample_count integer not null default 0,
          success_count integer not null default 0,
          failure_count integer not null default 0,
          duration_avg_ms integer not null default 0,
          duration_p50_ms integer not null default 0,
          duration_p95_ms integer not null default 0,
          duration_p99_ms integer not null default 0,
          duration_min_ms integer not null default 0,
          duration_max_ms integer not null default 0,
          ttft_avg_ms integer not null default 0,
          ttft_p50_ms integer not null default 0,
          ttft_p95_ms integer not null default 0,
          tps_avg real not null default 0,
          tps_max real not null default 0,
          built_at text not null
        );

        create virtual table if not exists conversation_messages_fts using fts5(
          content,
          conversation_ref unindexed,
          role unindexed,
          fact_id unindexed,
          tokenize = 'trigram'
        );

"""


def default_db_path() -> Path:
    env_path = os.environ.get("AGENT_OBSERVER_DB")
    if env_path:
        return Path(env_path)
    # 基于 connection.py 位置（backend/app/db/connection.py）计算绝对路径，
    # 避免相对路径依赖 CWD 导致不同启动方式写入不同数据库。
    return Path(__file__).resolve().parent.parent.parent / "data" / "agent-observer.sqlite"


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


# 全局写锁：所有写操作经此锁串行化，避免多连接在 SQLite 层抢写锁导致
# OperationalError: database is locked。RLock 允许同线程嵌套获取（防死锁）。
_WRITE_LOCK = threading.RLock()


@contextmanager
def write_lock(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """写事务上下文：获取全局写锁 → 返回独立连接 → 异常时 rollback。

    把 SQLite 层的锁等待（busy_timeout 超时后抛 OperationalError）换成应用层
    有序排队（不超时）。读端点继续用 connect()，WAL 下读不阻塞写。

    用法：
        with write_lock() as conn:
            ingest_telemetry(conn, batch)  # service 内部自行 commit
    """
    with _WRITE_LOCK:
        with connect(db_path) as conn:
            try:
                yield conn
            except Exception:
                # service 内部可能已部分写入但未 commit，rollback 防止脏状态
                # 污染下一次 write_lock（连接虽关闭，但未 rollback 的脏数据可能
                # 在连接池/缓存中残留——显式 rollback 更安全）。
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise


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
          (id, policy_version, enrichment_mode, collection_interval_seconds, max_events_per_cycle, upload_batch_size, worker_poll_interval_seconds, outbox_soft_limit, log_level)
        values (1, 1, 'enabled', 10, 500, 100, 10, 5000, 'INFO')
        """
    )


def _ensure_effective_policy_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("pragma table_info(effective_policies)").fetchall()}
    if "collection_interval_seconds" not in columns:
        conn.execute("alter table effective_policies add column collection_interval_seconds integer not null default 10")
    if "max_events_per_cycle" not in columns:
        conn.execute("alter table effective_policies add column max_events_per_cycle integer not null default 500")
    if "upload_batch_size" not in columns:
        conn.execute("alter table effective_policies add column upload_batch_size integer not null default 100")
    if "worker_poll_interval_seconds" not in columns:
        conn.execute("alter table effective_policies add column worker_poll_interval_seconds integer not null default 10")
    if "outbox_soft_limit" not in columns:
        conn.execute("alter table effective_policies add column outbox_soft_limit integer not null default 5000")
    if "log_level" not in columns:
        conn.execute("alter table effective_policies add column log_level text not null default 'INFO'")


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
        create index if not exists idx_observed_facts_source_event_type_occurred_at
          on observed_facts(source_event_type, occurred_at desc);
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
        create index if not exists idx_risk_signals_fact_id
          on risk_signals(fact_id);
        create index if not exists idx_risk_signals_risk_type_object_type
          on risk_signals(risk_type, object_type);
        create index if not exists idx_risk_signals_severity
          on risk_signals(severity);
        create index if not exists idx_usage_signals_fact_id
          on usage_signals(fact_id);
        create index if not exists idx_behavior_signals_decision_priority_last_event
          on behavior_signals(decision_state, priority_score desc, last_event_at desc);
        create index if not exists idx_signal_decisions_decision_state
          on signal_decisions(decision_state);
        create index if not exists idx_enrichment_jobs_signal_id
          on enrichment_jobs(signal_id);
        create index if not exists idx_enrichment_results_signal_id
          on enrichment_results(signal_id);
        create index if not exists idx_conversations_last_event
          on conversations(last_event_at desc);
        create index if not exists idx_conversations_agent_last_event
          on conversations(agent_type, last_event_at desc);
        create index if not exists idx_conversations_source_last_event
          on conversations(source_id, last_event_at desc);
        create index if not exists idx_conversations_base_path
          on conversations(base_ref, source_path_hash);
        create index if not exists idx_conversations_started_at
          on conversations(started_at);
        create index if not exists idx_conv_messages_ref_occurred
          on conversation_messages(conversation_ref, occurred_at, fact_id);
        create index if not exists idx_conv_messages_base_path_line
          on conversation_messages(base_ref, source_path_hash, source_line);
        create index if not exists idx_conv_hits_ref_occurred
          on conversation_hits(conversation_ref, occurred_at, fact_id);
        create index if not exists idx_conv_hits_base_path
          on conversation_hits(base_ref, source_path_hash, source_line);
        create index if not exists idx_perf_signals_span_type_occurred
          on perf_signals(span_type, occurred_at desc);
        create index if not exists idx_perf_signals_agent_occurred
          on perf_signals(agent_type, occurred_at desc);
        create index if not exists idx_perf_signals_trace_id
          on perf_signals(trace_id);
        create index if not exists idx_perf_signals_conversation
          on perf_signals(conversation_ref, occurred_at desc);
        create index if not exists idx_perf_signals_fact_id
          on perf_signals(fact_id);
        create index if not exists idx_perf_rollups_window_scope
          on perf_rollups(window, scope, scope_value, span_type);
        """
    )


