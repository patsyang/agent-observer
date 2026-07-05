import type { Collector } from './types.collectors';
import type { ObservedFact, TimeWindowParam } from './types.facts';
import type { BehaviorSignal } from './types.signals';
import type { RiskSummarySignal } from './types.usage';

export interface DashboardSummary {
  window: TimeWindowParam;
  collectors: {
    total: number;
    online: number;
    degraded: number;
    offline: number;
    items: Collector[];
  };
  signals: {
    total: number;
    items: BehaviorSignal[];
    high_priority_count?: number;
  };
  facts: {
    total: number;
    items: ObservedFact[];
    time_basis?: 'occurred' | 'ingested';
  };
  risks: {
    top: RiskSummarySignal[];
    total: number;
  };
}
