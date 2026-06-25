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
  HandleSignalPayload,
  BehaviorSignalDetail,
  PolicyUpdatePayload,
  ProcessingStatus,
  RecentAuditSummary,
  RiskSummary,
  SignalsResponse,
  TimeWindow,
  TimeWindowParam,
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

type AgentTypeFilter = '' | 'codex' | 'workbuddy';

function addAgentFilter(params: URLSearchParams, agentType?: AgentTypeFilter | string): void {
  if (agentType) params.set('agent_type', agentType);
}

function addTimeRange(params: URLSearchParams, window: TimeWindowParam | '' = '1h', startAt = '', endAt = ''): void {
  params.set('window', window || (startAt || endAt ? 'custom' : '1h'));
  if (startAt) params.set('start_at', startAt);
  if (endAt) params.set('end_at', endAt);
}

export function fetchDashboardSummary(
  window: TimeWindowParam = '1h',
  agentType: AgentTypeFilter = '',
  startAt = '',
  endAt = ''
): Promise<DashboardSummary> {
  const params = new URLSearchParams();
  addTimeRange(params, window, startAt, endAt);
  addAgentFilter(params, agentType);
  return readJson<DashboardSummary>(`/api/dashboard/summary?${params.toString()}`);
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

export function fetchProcessingStatus(): Promise<ProcessingStatus> {
  return readJson<ProcessingStatus>('/api/processing/status');
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
    workspace_query?: string;
    agent_type?: string;
    source_id?: string;
    page?: number;
    page_size?: number;
  } = {}
): Promise<ConversationsResponse> {
  const params = new URLSearchParams();
  if (filters.window) {
    params.set('window', filters.window);
  } else if (filters.start_at || filters.end_at) {
    params.set('window', 'custom');
  }
  if (filters.start_at) params.set('start_at', filters.start_at);
  if (filters.end_at) params.set('end_at', filters.end_at);
  if (filters.prompt_query) params.set('prompt_query', filters.prompt_query);
  if (filters.response_query) params.set('response_query', filters.response_query);
  if (filters.workspace_query) params.set('workspace_query', filters.workspace_query);
  if (filters.agent_type) params.set('agent_type', filters.agent_type);
  if (filters.source_id) params.set('source_id', filters.source_id);
  params.set('page', String(filters.page ?? 1));
  params.set('page_size', String(filters.page_size ?? 20));
  return readJson<ConversationsResponse>(`/api/conversations?${params.toString()}`);
}

export function fetchConversationDetail(conversationRef: string): Promise<ConversationDetail> {
  return readJson<ConversationDetail>(`/api/conversations/${encodeURIComponent(conversationRef)}`);
}

export function fetchConversationForFact(factId: string): Promise<ConversationDetail> {
  return readJson<ConversationDetail>(`/api/conversations/by-fact/${encodeURIComponent(factId)}`);
}

export function fetchUsageSummary(
  window: TimeWindowParam = '1h',
  agentType: AgentTypeFilter = '',
  startAt = '',
  endAt = ''
): Promise<UsageSummary> {
  const params = new URLSearchParams();
  addTimeRange(params, window, startAt, endAt);
  addAgentFilter(params, agentType);
  return readJson<UsageSummary>(`/api/usage/summary?${params.toString()}`);
}

export function fetchRiskSummary(
  window: TimeWindowParam = '1h',
  agentType: AgentTypeFilter = '',
  startAt = '',
  endAt = ''
): Promise<RiskSummary> {
  const params = new URLSearchParams();
  params.set('mode', 'summary');
  addTimeRange(params, window, startAt, endAt);
  addAgentFilter(params, agentType);
  return readJson<RiskSummary>(`/api/risks/summary?${params.toString()}`);
}

export function fetchSignals(
  options: {
    window?: TimeWindowParam | '';
    start_at?: string;
    end_at?: string;
    workspace_query?: string;
    agent_type?: AgentTypeFilter | string;
    page?: number;
    page_size?: number;
  } = {}
): Promise<SignalsResponse> {
  const params = new URLSearchParams();
  addTimeRange(params, options.window ?? '1h', options.start_at, options.end_at);
  if (options.workspace_query) params.set('workspace_query', options.workspace_query);
  addAgentFilter(params, options.agent_type);
  params.set('page', String(options.page ?? 1));
  params.set('page_size', String(options.page_size ?? 20));
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return readJson<SignalsResponse>(`/api/signals${suffix}`);
}

export function fetchSignalDetail(signalId: string): Promise<BehaviorSignalDetail> {
  return readJson<BehaviorSignalDetail>(`/api/signals/${signalId}`);
}

export function markSignalRead(signalId: string): Promise<BehaviorSignalDetail> {
  return postJson<BehaviorSignalDetail>(`/api/signals/${signalId}/read`);
}

export function handleSignal(signalId: string, payload: HandleSignalPayload): Promise<BehaviorSignalDetail> {
  return postJson<BehaviorSignalDetail>(`/api/signals/${signalId}/handle`, payload);
}

export function fetchEnrichmentAvailability(signalId: string): Promise<EnrichmentAvailability> {
  return readJson<EnrichmentAvailability>(`/api/signals/${signalId}/enrichments/availability`);
}

export function requestEnrichment(signalId: string, capabilityId: string): Promise<EnrichmentJob> {
  return postJson<EnrichmentJob>(`/api/signals/${signalId}/enrichments`, { capability_id: capabilityId });
}

export function cancelEnrichment(jobId: string): Promise<EnrichmentJob> {
  return postJson<EnrichmentJob>(`/api/enrichments/${jobId}/cancel`);
}
