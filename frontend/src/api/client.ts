import type {
  ClientPackageConfig,
  DiagnosticAvailability,
  DiagnosticJob,
  CollectorsResponse,
  EffectivePolicy,
  FactDetail,
  FactsResponse,
  FactQuality,
  HandleStoryPayload,
  ObservationStoryDetail,
  PolicyUpdatePayload,
  RecentAuditSummary,
  RiskSummary,
  StoriesResponse,
  TimeWindow,
  UsageSummary
} from './types';

const apiBase = import.meta.env.VITE_API_BASE_URL ?? '';

async function readJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, payload: unknown = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function patchJson<T>(path: string, payload: unknown = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchCollectors(): Promise<CollectorsResponse> {
  return readJson<CollectorsResponse>('/api/collectors');
}

export function deleteCollector(collectorId: string): Promise<{ collector_id: string; removed: boolean; reason_code: string }> {
  return deleteJson(`/api/collectors/${encodeURIComponent(collectorId)}`);
}

export function updateCollectorRawUpload(
  collectorId: string,
  enabled: boolean
): Promise<{ collector_id: string; raw_upload_enabled: boolean; raw_upload_override: boolean; raw_upload_source: string }> {
  return patchJson(`/api/collectors/${encodeURIComponent(collectorId)}/raw-upload`, { enabled });
}

export function fetchClientPackageConfig(): Promise<ClientPackageConfig> {
  return readJson<ClientPackageConfig>('/api/client-package/config');
}

export function fetchPolicy(): Promise<EffectivePolicy> {
  return readJson<EffectivePolicy>('/api/policy');
}

export function updatePolicy(payload: PolicyUpdatePayload): Promise<EffectivePolicy> {
  return patchJson<EffectivePolicy>('/api/policy', payload);
}

export function fetchRecentAudit(): Promise<RecentAuditSummary> {
  return readJson<RecentAuditSummary>('/api/audit/recent');
}

export function clientPackageUrl(): string {
  return `${apiBase}/api/client-package/windows`;
}

export function fetchFacts(
  filters: {
    quality?: FactQuality | 'all';
    fact_type?: string;
    source?: string;
    window?: TimeWindow;
    include_health?: boolean;
    limit?: number;
    offset?: number;
  } = {}
): Promise<FactsResponse> {
  const params = new URLSearchParams();
  if (filters.quality && filters.quality !== 'all') params.set('quality', filters.quality);
  if (filters.fact_type && filters.fact_type !== 'all') params.set('fact_type', filters.fact_type);
  if (filters.source && filters.source !== 'all') params.set('source', filters.source);
  params.set('window', filters.window ?? '1h');
  params.set('include_health', String(filters.include_health ?? false));
  params.set('limit', String(filters.limit ?? 50));
  params.set('offset', String(filters.offset ?? 0));
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return readJson<FactsResponse>(`/api/facts${suffix}`);
}

export function fetchFactDetail(factId: string): Promise<FactDetail> {
  return readJson<FactDetail>(`/api/facts/${factId}`);
}

export function fetchUsageSummary(window: TimeWindow = '1h'): Promise<UsageSummary> {
  return readJson<UsageSummary>(`/api/usage/summary?window=${encodeURIComponent(window)}`);
}

export function fetchRiskSummary(window: TimeWindow = '1h'): Promise<RiskSummary> {
  return readJson<RiskSummary>(`/api/risks/summary?mode=summary&window=${encodeURIComponent(window)}`);
}

export function fetchStories(options: { includeHidden?: boolean; window?: TimeWindow; queue?: 'actionable' | 'all' } = {}): Promise<StoriesResponse> {
  const params = new URLSearchParams();
  if (options.includeHidden) params.set('include_hidden', 'true');
  params.set('window', options.window ?? '1h');
  params.set('queue', options.queue ?? 'actionable');
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return readJson<StoriesResponse>(`/api/stories${suffix}`);
}

export function fetchStoryDetail(storyId: string): Promise<ObservationStoryDetail> {
  return readJson<ObservationStoryDetail>(`/api/stories/${storyId}`);
}

export function markStoryRead(storyId: string): Promise<ObservationStoryDetail> {
  return postJson<ObservationStoryDetail>(`/api/stories/${storyId}/read`);
}

export function handleStory(storyId: string, payload: HandleStoryPayload): Promise<ObservationStoryDetail> {
  return postJson<ObservationStoryDetail>(`/api/stories/${storyId}/handle`, payload);
}

export function fetchDiagnosticAvailability(storyId: string): Promise<DiagnosticAvailability> {
  return readJson<DiagnosticAvailability>(`/api/stories/${storyId}/diagnostics/availability`);
}

export function requestDiagnostic(storyId: string, capabilityId: string): Promise<DiagnosticJob> {
  return postJson<DiagnosticJob>(`/api/stories/${storyId}/diagnostics`, { capability_id: capabilityId });
}

export function cancelDiagnostic(jobId: string): Promise<DiagnosticJob> {
  return postJson<DiagnosticJob>(`/api/diagnostics/${jobId}/cancel`);
}
