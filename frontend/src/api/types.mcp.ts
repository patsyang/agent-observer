export interface McpCallItem {
  fact_id: string;
  occurred_at: string;
  conversation_ref: string;
  mcp_server: string;
  mcp_tool: string;
  mcp_duration_ms: number;
  mcp_is_error: boolean;
  argument_keys: string[];
  risk_signals: string[];
}

export interface McpCallSummary {
  servers: string[];
  total_calls: number;
  error_calls: number;
  risk_calls: number;
}

export interface McpCallsResponse {
  items: McpCallItem[];
  total: number;
  page: number;
  page_size: number;
  summary: McpCallSummary;
}
