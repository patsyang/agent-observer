import type { TimeWindow } from './types.facts';

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
