import type { WorkspaceScope } from './types.conversations';

export type DecisionState = 'unread' | 'read' | 'needs_review' | 'handled';

export interface SignalUsageSummary {
  effective_units: number;
  cached_units?: number;
  cache_hit_rate?: number | null;
  no_usage_reason: string | null;
}

export interface EnrichmentStatusSummary {
  status: string;
  reason_code: string | null;
}

export type EnrichmentCapabilityState = 'available' | 'queueable' | 'unavailable';

export interface EnrichmentCapability {
  capability_id: string;
  label: string;
  state: EnrichmentCapabilityState;
  reason_code: string | null;
}

export interface EnrichmentJob {
  job_id: string;
  signal_id?: string;
  capability_id: string;
  status: string;
  reason_code?: string | null;
}

export interface EnrichmentAvailability {
  signal_id?: string;
  active_job?: EnrichmentJob | null;
  capabilities: EnrichmentCapability[];
}

export interface SignalEvidenceItem {
  evidence_ref: string;
  fact_id?: string | null;
  category: string;
  quality: string;
  fact_type: string;
  occurred_at?: string | null;
  summary: string;
  conversation_ref?: string;
  source_event_type: string;
  source_label: string;
  content_preview?: string;
  raw_available?: boolean;
  raw_status?: string;
  risk_category_count?: number;
  sensitive_categories?: string[];
  tool_name?: string | null;
  exit_code?: string | number | null;
  tool_context?: ToolContext | null;
}

export interface ToolContext {
  tool_name: string;
  command: string;
  command_excerpt: string;
  command_category: string;
  exit_code: string | number | null;
  is_timeout: boolean;
  timeout_ms: number | null;
  timeout_after_ms: number | null;
  wall_time_seconds: number | null;
  error_excerpt: string;
  call_id: string;
}

export interface SignalEvidenceGroup {
  group_id: string;
  group_type: 'conversation' | 'object' | 'failure' | string;
  title: string;
  summary: string;
  count: number;
  items: SignalEvidenceItem[];
}

export interface LinkedConversation {
  conversation_ref: string;
  session_ref?: string;
  session_title?: string;
  workspace?: WorkspaceScope;
  hit_count: number;
  last_seen_at?: string | null;
  matched_fact_ids?: string[];
}

export interface SignalWorkspaceSummary {
  mode: 'single' | 'multiple' | 'unknown' | string;
  label: string;
  count: number;
}

export interface SignalWorkspaceRef {
  agent_type?: string;
  workspace_id: string;
  workspace_path: string;
  workspace_label: string;
  workspace_alias_source?: string;
  workspace_confidence?: string;
}

export interface BehaviorSignal {
  signal_id: string;
  signal_key: string;
  signal_kind: string;
  title: string;
  why_it_matters: string;
  severity: string;
  confidence: string;
  priority_score: number;
  affected_scope: Record<string, unknown>;
  evidence_groups: SignalEvidenceGroup[];
  linked_conversations: LinkedConversation[];
  workspace_refs: SignalWorkspaceRef[];
  workspace_summary: SignalWorkspaceSummary;
  usage_summary: SignalUsageSummary;
  enrichment_status_summary: EnrichmentStatusSummary;
  suggested_actions: string[];
  decision_state: DecisionState;
  conclusion_code: string | null;
  note: string | null;
  snapshot_hash: string;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  last_event_at?: string | null;
  occurrence_count?: number;
  latest_fact_id?: string | null;
  latest_summary?: string | null;
}

export interface SignalsResponse {
  signals: BehaviorSignal[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
}

export type BehaviorSignalDetail = BehaviorSignal;

export interface HandleSignalPayload {
  conclusion_code: 'known_issue' | 'needs_fix' | 'accepted_risk' | 'expected_nonzero_exit' | 'duplicate_signal' | 'not_actionable' | '';
  note?: string;
}
