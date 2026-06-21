import type {
  ClientPackageConfig,
  ConversationTimeWindow,
  ConversationDetail,
  ConversationsResponse,
  EnrichmentAvailability,
  EnrichmentJob,
  CollectorsResponse,
  DashboardSummary,
  EffectivePolicy,
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

export function fetchDashboardSummary(window: TimeWindow = '1h'): Promise<DashboardSummary> {
  return readJson<DashboardSummary>(`/api/dashboard/summary?window=${encodeURIComponent(window)}`);
}

export function deleteCollector(collectorId: string): Promise<{ collector_id: string; removed: boolean; reason_code: string }> {
  return deleteJson(`/api/collectors/${encodeURIComponent(collectorId)}`);
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

export function fetchConversations(
  filters: {
    window?: ConversationTimeWindow | '';
    start_at?: string;
    end_at?: string;
    prompt_query?: string;
    response_query?: string;
    page?: number;
    page_size?: number;
  } = {}
): Promise<ConversationsResponse> {
  const params = new URLSearchParams();
  if (filters.window) params.set('window', filters.window);
  if (filters.start_at) params.set('start_at', filters.start_at);
  if (filters.end_at) params.set('end_at', filters.end_at);
  if (filters.prompt_query) params.set('prompt_query', filters.prompt_query);
  if (filters.response_query) params.set('response_query', filters.response_query);
  params.set('page', String(filters.page ?? 1));
  params.set('page_size', String(filters.page_size ?? 50));
  return readJson<ConversationsResponse>(`/api/conversations?${params.toString()}`);
}

export function fetchConversationDetail(conversationRef: string): Promise<ConversationDetail> {
  return readJson<ConversationDetail>(`/api/conversations/${encodeURIComponent(conversationRef)}`);
}

export function fetchConversationForFact(factId: string): Promise<ConversationDetail> {
  return readJson<ConversationDetail>(`/api/conversations/by-fact/${encodeURIComponent(factId)}`);
}

export function fetchUsageSummary(window: TimeWindow = '1h'): Promise<UsageSummary> {
  return readJson<UsageSummary>(`/api/usage/summary?window=${encodeURIComponent(window)}`);
}

export function fetchRiskSummary(window: TimeWindow = '1h'): Promise<RiskSummary> {
  return readJson<RiskSummary>(`/api/risks/summary?mode=summary&window=${encodeURIComponent(window)}`);
}

export function fetchStories(
  options: { includeHidden?: boolean; window?: TimeWindow; queue?: 'actionable' | 'all'; page?: number; page_size?: number } = {}
): Promise<StoriesResponse> {
  const params = new URLSearchParams();
  if (options.includeHidden) params.set('include_hidden', 'true');
  params.set('window', options.window ?? '1h');
  params.set('queue', options.queue ?? 'actionable');
  params.set('page', String(options.page ?? 1));
  params.set('page_size', String(options.page_size ?? 20));
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

export function fetchEnrichmentAvailability(storyId: string): Promise<EnrichmentAvailability> {
  return readJson<EnrichmentAvailability>(`/api/stories/${storyId}/enrichments/availability`);
}

export function requestEnrichment(storyId: string, capabilityId: string): Promise<EnrichmentJob> {
  return postJson<EnrichmentJob>(`/api/stories/${storyId}/enrichments`, { capability_id: capabilityId });
}

export function cancelEnrichment(jobId: string): Promise<EnrichmentJob> {
  return postJson<EnrichmentJob>(`/api/enrichments/${jobId}/cancel`);
}
