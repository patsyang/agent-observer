import type { Collector } from './types.collectors';
import type { ObservedFact, TimeWindow } from './types.facts';
import type { ObservationStory } from './types.stories';
import type { RiskSummarySignal } from './types.usage';

export interface DashboardSummary {
  window: TimeWindow;
  collectors: {
    total: number;
    online: number;
    degraded: number;
    offline: number;
    items: Collector[];
  };
  stories: {
    total: number;
    items: ObservationStory[];
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
