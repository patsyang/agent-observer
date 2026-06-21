export type HandlingState = 'unread' | 'read' | 'handled';
export type AttentionState = 'active' | 'handled_hidden' | 'needs_review';

export interface StoryUsageSummary {
  effective_units: number;
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
  story_id?: string;
  capability_id: string;
  status: string;
  reason_code?: string | null;
}

export interface EnrichmentAvailability {
  story_id?: string;
  active_job?: EnrichmentJob | null;
  capabilities: EnrichmentCapability[];
}

export interface ObservationStory {
  story_id: string;
  story_key: string;
  conclusion: string;
  impact_objects: string[];
  evidence_refs: string[];
  usage_summary: StoryUsageSummary;
  enrichment_status_summary: EnrichmentStatusSummary;
  handling_state: HandlingState;
  conclusion_code: string | null;
  handling_note: string | null;
  attention_state: AttentionState;
  priority_score: number;
  suggested_action: string;
  snapshot_hash: string;
  story_type?: string;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  last_event_at?: string | null;
  occurrence_count?: number;
  primary_object_type?: string | null;
  primary_object_value?: string | null;
  latest_fact_id?: string | null;
  latest_summary?: string | null;
}

export interface StoriesResponse {
  stories: ObservationStory[];
  total?: number;
  page?: number;
  page_size?: number;
  has_more?: boolean;
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
