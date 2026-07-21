/** 性能观测 API 客户端（对标 api/mcp.ts 的 readJson 模式）。 */
import { readJson } from './client';
import type {
  PerfCallTimelineResponse,
  PerfFailuresResponse,
  PerfSummary,
  PerfTaskDetail,
  PerfTasksResponse,
  PerfWindow,
} from './types.performance';

export type PerfAgentType = '' | 'codex' | 'workbuddy' | 'claude';

interface PerfParams {
  window?: PerfWindow;
  agent_type?: PerfAgentType;
}

function buildPerfParams(params: PerfParams): URLSearchParams {
  const search = new URLSearchParams();
  search.set('window', params.window ?? '24h');
  if (params.agent_type) search.set('agent_type', params.agent_type);
  return search;
}

export function fetchPerfSummary(params: PerfParams = {}): Promise<PerfSummary> {
  return readJson<PerfSummary>(`/api/performance/summary?${buildPerfParams(params).toString()}`);
}

export function fetchPerfTasks(
  params: PerfParams & { page?: number; page_size?: number } = {}
): Promise<PerfTasksResponse> {
  const search = buildPerfParams(params);
  search.set('page', String(params.page ?? 1));
  search.set('page_size', String(params.page_size ?? 20));
  return readJson<PerfTasksResponse>(`/api/performance/tasks?${search.toString()}`);
}

export function fetchPerfTaskDetail(traceId: string): Promise<PerfTaskDetail> {
  return readJson<PerfTaskDetail>(`/api/performance/tasks/${encodeURIComponent(traceId)}`);
}

export function fetchPerfCallTimeline(
  traceId: string,
  spanType?: string
): Promise<PerfCallTimelineResponse> {
  const search = new URLSearchParams();
  if (spanType) search.set('span_type', spanType);
  const suffix = search.toString() ? `?${search.toString()}` : '';
  return readJson<PerfCallTimelineResponse>(
    `/api/performance/tasks/${encodeURIComponent(traceId)}/calls${suffix}`
  );
}

export function fetchPerfFailures(params: PerfParams = {}): Promise<PerfFailuresResponse> {
  return readJson<PerfFailuresResponse>(
    `/api/performance/failures?${buildPerfParams(params).toString()}`
  );
}