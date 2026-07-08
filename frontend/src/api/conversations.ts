import type {
  ConversationDetail,
  ConversationHitsResponse,
  ConversationMessagesResponse,
  ConversationTimeWindow,
  ConversationsResponse,
  HitsByFactIdsResponse,
  MessageLocateResponse,
} from './types';
import { readJson } from './client';

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

export function fetchConversationMessages(
  conversationRef: string,
  role?: string,
  page = 1,
  pageSize = 50
): Promise<ConversationMessagesResponse> {
  const params = new URLSearchParams();
  if (role) params.set('role', role);
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  return readJson<ConversationMessagesResponse>(
    `/api/conversations/${encodeURIComponent(conversationRef)}/messages?${params.toString()}`
  );
}

export function fetchConversationHits(
  conversationRef: string,
  category?: string,
  page = 1,
  pageSize = 50
): Promise<ConversationHitsResponse> {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  return readJson<ConversationHitsResponse>(
    `/api/conversations/${encodeURIComponent(conversationRef)}/hits?${params.toString()}`
  );
}

export function locateConversationMessage(
  conversationRef: string,
  factId: string,
  pageSize = 50
): Promise<MessageLocateResponse> {
  const params = new URLSearchParams();
  params.set('fact_id', factId);
  params.set('page_size', String(pageSize));
  return readJson<MessageLocateResponse>(
    `/api/conversations/${encodeURIComponent(conversationRef)}/messages/locate?${params.toString()}`
  );
}

export function fetchConversationHitsByFactIds(
  conversationRef: string,
  factIds: string[]
): Promise<HitsByFactIdsResponse> {
  const params = new URLSearchParams();
  params.set('fact_ids', factIds.join(','));
  return readJson<HitsByFactIdsResponse>(
    `/api/conversations/${encodeURIComponent(conversationRef)}/hits/by-fact-ids?${params.toString()}`
  );
}
