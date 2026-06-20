export const sourceStatuses = [
  'online',
  'degraded',
  'offline',
  'source_missing',
  'source_locked'
] as const;

export type SourceStatus = (typeof sourceStatuses)[number];

export interface Collector {
  collector_id: string;
  display_name: string;
  hostname_hash: string;
  windows_username_hash: string;
  agent_type: string;
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
  raw_upload_enabled: boolean;
  raw_upload_override: boolean;
  raw_upload_source: 'global_policy' | 'collector_override';
}

export interface CollectorsResponse {
  collectors: Collector[];
}

export interface ClientPackageConfig {
  filename: string;
  path: string;
  config_path: string;
  sha256: string;
}

export interface EffectivePolicy {
  policy_version: number;
  template_enabled: boolean;
  upload_raw: boolean;
  collection_policy: string;
  diagnostic_policy: string;
}

export interface PolicyUpdatePayload {
  expected_version: number;
  template_enabled: boolean;
  upload_raw: boolean;
  collection_policy: string;
  diagnostic_policy: string;
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
