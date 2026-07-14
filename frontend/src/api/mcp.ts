import { readJson } from './client';
import type { McpCallsResponse } from './types.mcp';

export async function fetchMcpCalls(params: {
  page?: number;
  page_size?: number;
  server?: string;
  risk_only?: boolean;
  error_only?: boolean;
} = {}): Promise<McpCallsResponse> {
  const search = new URLSearchParams();
  if (params.page) search.set('page', String(params.page));
  if (params.page_size) search.set('page_size', String(params.page_size));
  if (params.server) search.set('server', params.server);
  if (params.risk_only) search.set('risk_only', 'true');
  if (params.error_only) search.set('error_only', 'true');
  return readJson<McpCallsResponse>(`/api/mcp/calls?${search.toString()}`);
}
