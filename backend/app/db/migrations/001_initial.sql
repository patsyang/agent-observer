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

create index if not exists idx_observed_facts_effective_conversation_path_occurred
  on observed_facts(
    coalesce(nullif(conversation_ref, ''), nullif(session_ref, ''), fact_id),
    source_path_hash,
    occurred_at
  );

create index if not exists idx_usage_signals_conversation_id
  on usage_signals(conversation_id);
