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
