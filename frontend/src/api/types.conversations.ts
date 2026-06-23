import type { TimeWindowParam } from './types.facts';
import type { ToolContext } from './types.signals';

export type ConversationTimeWindow = TimeWindowParam;

export interface ConversationUsage {
  effective_units: number;
  model_call_count?: number;
  max_single_call_units?: number;
  cached_input_units?: number;
  input_token_units?: number;
  output_token_units?: number;
  total_token_units?: number;
  cache_write_input_units?: number;
  reasoning_output_units?: number;
  credit_total?: number;
  cache_observed_input_units?: number;
  cache_hit_rate?: number;
}

export interface WorkspaceScope {
  agent_type?: string;
  workspace_id: string;
  workspace_path: string;
  workspace_label: string;
  workspace_alias_source?: string;
  workspace_confidence?: string;
}

export interface ConversationSummary {
  conversation_ref: string;
  session_ref: string;
  session_title: string;
  agent_type: string;
  source_id: string;
  source_kind: string;
  workspace: WorkspaceScope;
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
  tool_context?: ToolContext | null;
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
  agent_type?: string | null;
  source_id?: string | null;
}
