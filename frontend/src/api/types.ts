export const sourceStatuses = [
  'online',
  'offline',
  'source_missing',
  'source_locked',
  'state_corrupt',
  'outbox_backlog',
  'policy_not_fetched'
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

export type FactQuality = 'high' | 'low' | 'unknown';

export interface ObservedFact {
  fact_id: string;
  source_event_id?: string;
  fact_type: string;
  category: string;
  quality: FactQuality;
  severity: string;
  summary: string;
  occurred_at: string;
  source: string;
  promoted_to_story: boolean;
  source_event_type?: string;
  source_label?: string;
  content_preview?: string;
  raw_available?: boolean;
  raw_status?: string;
}

export type TimeWindow = '1h' | '24h' | '7d' | 'all';

export interface FactsResponse {
  facts: ObservedFact[];
  total?: number;
  limit?: number;
  offset?: number;
}

export interface EvidenceProjection {
  projection_id: string;
  fact_id: string;
  category: string;
  span: string;
  raw_hash: string;
  projection_json: Record<string, unknown>;
  upload_raw: boolean;
  raw_content: string | null;
}

export interface FactDetail {
  fact: ObservedFact;
  evidence_projection: EvidenceProjection;
  evidence_projections: EvidenceProjection[];
  source_refs: Record<string, unknown>;
  source_specific_json: Record<string, unknown>;
}

export type UsageKind = 'associated' | 'attributed';

export interface UsageRollup {
  rollup_id: string;
  window: string;
  scope: 'total' | 'session' | 'conversation' | 'project' | 'account' | 'activity_tag';
  scope_value: string;
  units: number;
  usage_kind: UsageKind;
  activity_tag: string;
  additive: boolean;
  evidence_refs: string[];
}

export interface UsageSummary {
  window: string;
  rollups: UsageRollup[];
  totals: {
    associated_units: number;
    attributed_units: number;
    unknown_units: number;
  };
}

export interface RiskSummarySignal {
  risk_type: string;
  object_type: string;
  count: number;
  highest_severity: string;
  top_examples?: string[];
  first_seen_at?: string;
  last_seen_at?: string;
  evidence_refs?: string[];
  trend?: Array<{ occurred_at: string; severity: string }>;
}

export interface RiskSummary {
  mode?: 'summary' | 'detailed';
  window?: TimeWindow;
  signals: RiskSummarySignal[];
}

export type HandlingState = 'unread' | 'read' | 'handled';
export type AttentionState = 'active' | 'handled_hidden' | 'needs_review';

export interface StoryUsageSummary {
  attributed_units: number;
  associated_units: number;
  no_usage_reason: string | null;
}

export interface DiagnosticStatusSummary {
  status: string;
  reason_code: string | null;
}

export type DiagnosticCapabilityState = 'available' | 'queueable' | 'unavailable';

export interface DiagnosticCapability {
  capability_id: string;
  label: string;
  state: DiagnosticCapabilityState;
  reason_code: string | null;
}

export interface DiagnosticJob {
  job_id: string;
  story_id?: string;
  capability_id: string;
  status: string;
  reason_code?: string | null;
}

export interface DiagnosticAvailability {
  story_id?: string;
  active_job?: DiagnosticJob | null;
  capabilities: DiagnosticCapability[];
}

export interface ObservationStory {
  story_id: string;
  story_key: string;
  conclusion: string;
  impact_objects: string[];
  evidence_refs: string[];
  usage_summary: StoryUsageSummary;
  diagnostic_status_summary: DiagnosticStatusSummary;
  handling_state: HandlingState;
  conclusion_code: string | null;
  handling_note: string | null;
  attention_state: AttentionState;
  priority_score: number;
  suggested_action: string;
  snapshot_hash: string;
}

export interface StoriesResponse {
  stories: ObservationStory[];
}

export interface StoryEvidenceEntry {
  evidence_ref: string;
  fact_id?: string | null;
  category: string;
  summary: string;
  quality: string;
  occurred_at?: string;
  fact_type?: string;
  source_event_type?: string;
  source_label?: string;
  content_preview?: string;
  raw_available?: boolean;
  raw_status?: string;
  risk_object?: string;
  risk_object_type?: string;
  risk_category_count?: number;
  sensitive_categories?: string[];
}

export interface ObservationStoryDetail extends ObservationStory {
  current_snapshot: {
    evidence_chain: StoryEvidenceEntry[];
    source_refs: Array<Record<string, unknown>>;
  };
  recent_audit_summary: {
    latest: string;
    events: Array<{
      action: string;
      actor: string;
      created_at: string;
      metadata: Record<string, unknown>;
    }>;
  };
}

export interface HandleStoryPayload {
  conclusion_code: 'known_issue' | 'needs_fix' | 'accepted_risk' | 'not_actionable' | '';
  note?: string;
}
