import type { TimeWindow } from './types.facts';

export interface UsageRollup {
  rollup_id: string;
  window: string;
  scope: 'total' | 'session' | 'conversation' | 'project' | 'account' | 'activity_tag';
  scope_value: string;
  units: number;
  activity_tag: string;
  evidence_refs: string[];
}

export interface UsageSummary {
  window: string;
  rollups: UsageRollup[];
  trend: Array<{
    bucket: string;
    effective_units: number;
    unknown_units: number;
    cached_input_units: number;
    input_token_units: number;
    cache_hit_rate: number;
  }>;
  totals: {
    effective_units: number;
    unknown_units: number;
    cached_input_units: number;
    input_token_units: number;
    cache_hit_rate: number;
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
