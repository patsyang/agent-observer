export const sourceStatuses = [
  'online',
  'degraded',
  'offline',
  'source_missing',
  'source_locked'
] as const;

export type SourceStatus = (typeof sourceStatuses)[number];

export interface AgentSource {
  source_id: string;
  collector_id: string;
  agent_type: string;
  source_kind: string;
  display_name: string;
  capabilities: Record<string, unknown>;
  source_status: SourceStatus;
  reason_code: string;
  last_seen_at: string | null;
}

export interface Collector {
  collector_id: string;
  display_name: string;
  hostname_hash: string;
  windows_username_hash: string;
  protocol_version: string;
  agent_version: string;
  source_status: SourceStatus;
  reason_code: string;
  policy_version: number;
  last_heartbeat_at: string | null;
  last_seen_at?: string | null;
  runtime_phase?: 'starting' | 'idle' | 'collecting' | 'uploading' | 'waiting' | 'backfilling' | 'stopping';
  last_cycle_duration_ms?: number | null;
  last_error?: string | null;
  outbox_backlog: number;
  sources: AgentSource[];
}

export interface CollectorsResponse {
  collectors: Collector[];
}

export interface ClientPackageConfig {
  filename: string;
  path: string;
  sha256: string;
  server_url: string;
  agent_version: string;
  protocol_version: string;
}

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';

export interface EffectivePolicy {
  policy_version: number;
  raw_upload_mode: 'always_on';
  enrichment_mode: 'disabled' | 'enabled';
  log_level: LogLevel;
  collection_interval_seconds: number;
  max_events_per_cycle: number;
  upload_batch_size: number;
  worker_poll_interval_seconds: number;
  outbox_soft_limit?: number;
}

export interface PolicyUpdatePayload {
  expected_version: number;
  enrichment_mode: 'disabled' | 'enabled';
  log_level: LogLevel;
  collection_interval_seconds: number;
  max_events_per_cycle: number;
  upload_batch_size: number;
  worker_poll_interval_seconds: number;
}

export interface AuditEvent {
  object_type: string;
  object_id: string;
  action: string;
  actor: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface RecentAuditSummary {
  latest: string;
  events: AuditEvent[];
}

export interface ProcessingStatus {
  state: 'idle' | 'pending' | 'running' | 'failed';
  counts: Record<'pending' | 'running' | 'succeeded' | 'failed', number>;
  latest_failed: { job_id: string; last_error: string; updated_at: string } | null;
}
