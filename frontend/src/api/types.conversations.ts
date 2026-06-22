import type { TimeWindow } from './types.facts';

export type ConversationTimeWindow = TimeWindow | '2h' | '3h' | 'today';

export interface ConversationUsage {
  effective_units: number;
  model_call_count?: number;
  max_single_call_units?: number;
  cached_input_units?: number;
  input_token_units?: number;
  cache_hit_rate?: number;
}

export interface ConversationSummary {
  conversation_ref: string;
  session_ref: string;
  session_title: string;
  started_at: string;
  last_event_at: string;
  prompt_preview: string;
  response_preview: string;
  event_count: number;
  hit_count: number;
  token_usage: ConversationUsage;
}

export interface ConversationMessage {
  fact_id: string;
  role: string;
  category: string;
  occurred_at: string;
  content: string;
  raw_available: boolean;
}

export interface ConversationHit {
  fact_id: string;
  category: string;
  fact_type: string;
  severity: string;
  occurred_at: string;
  summary: string;
  content_preview: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[];
  hits: ConversationHit[];
}

export interface ConversationsResponse {
  conversations: ConversationSummary[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  window: ConversationTimeWindow;
  start_at?: string | null;
  end_at?: string | null;
}
