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

export interface EffectivePolicy {
  policy_version: number;
  raw_upload_mode: 'always_on';
  enrichment_mode: 'disabled' | 'enabled';
}

export interface PolicyUpdatePayload {
  expected_version: number;
  enrichment_mode: 'disabled' | 'enabled';
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
