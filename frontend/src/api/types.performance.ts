/** 性能观测 API 类型定义（对标 backend/app/perf/service.py 返回结构）。 */

/** 后端合法的 window 值（见 service.py _VALID_WINDOWS）。 */
export type PerfWindow = '1h' | '2h' | '3h' | '6h' | '12h' | '24h' | '7d' | 'today' | 'week' | 'all';

/** 延迟统计：百分位 + TTFT + TPS。 */
export interface PerfLatencyStats {
  sample_count: number;
  success_count: number;
  failure_count: number;
  duration_avg_ms: number;
  duration_p50_ms: number;
  duration_p95_ms: number;
  duration_p99_ms: number;
  duration_min_ms: number;
  duration_max_ms: number;
  ttft_avg_ms: number;
  ttft_p50_ms: number;
  ttft_p95_ms: number;
  tps_avg: number;
  tps_max: number;
}

/** 顶部汇总卡数据。 */
export interface PerfSummary {
  window: PerfWindow;
  bucket_size_minutes: number;
  totals: {
    task_count: number;
    llm_call_count: number;
    tool_call_count: number;
    success_count: number;
    failure_count: number;
    success_rate: number;
  };
  /** key = span_type（llm_call / tool_call / task / mcp_call）。 */
  latency: Record<string, PerfLatencyStats>;
  sample_count: number;
  /** M2: 截断标志——window=all 且信号数 > 50000 时为 true，延迟统计基于最近 50000 条。 */
  truncated?: boolean;
}

/** 任务列表行（按 trace_id 分组）。 */
export interface PerfTaskRow {
  trace_id: string;
  started_at: string;
  ended_at: string;
  call_count: number;
  llm_call_count: number;
  tool_call_count: number;
  success_count: number;
  failure_count: number;
  total_duration_ms: number;
  agent_type: string;
  conversation_ref: string;
  /** 任务关联的 fact_id（优先取 task span 的 fact_id），用于跳转会话详情。 */
  fact_id: string;
  task_duration_ms: number;
  /** 任务 span 的 error 原文（如 interrupted），用于区分"中断"与"失败"。 */
  task_error: string;
  task_status: string;
}

export interface PerfTasksResponse {
  window: PerfWindow;
  page: number;
  page_size: number;
  total: number;
  tasks: PerfTaskRow[];
}

/** 单个 span 明细。 */
export interface PerfSpan {
  signal_id: string;
  /** span 关联的 fact_id，用于跳转到会话详情定位具体调用。 */
  fact_id: string;
  span_id: string;
  parent_span_id: string;
  span_type: string;
  span_name: string;
  duration_ms: number;
  ttft_ms: number;
  tps: number;
  status: string;
  error: string;
  model: string;
  tool_name: string;
  occurred_at: string;
}

/** 任务详情抽屉内的会话期间关键事件（risk/error 类型 fact）。 */
export interface PerfContextEvent {
  fact_id: string;
  fact_type: 'risk' | 'error' | string;
  category: string;
  normalized_event_type: string;
  severity: string;
  summary: string;
  occurred_at: string;
}

export interface PerfTaskDetail {
  trace_id: string;
  task: PerfSpan | null;
  spans: PerfSpan[];
  agent_type: string;
  conversation_ref: string;
  started_at: string;
  ended_at: string;
  call_count: number;
  /** 任务整体状态（rolled up from children，与任务列表一致）。 */
  task_status: string;
  /** P1-1: rolled-up task_error（与任务列表同口径），抽屉元数据状态标签用此字段，
   * 避免 task span 自身 error 为空但子 span interrupted 时列表显示"已中断"而抽屉显示"失败"。 */
  task_error: string;
  /** 会话期间关键事件（文件变更、破坏性操作、工具失败等），帮助用户理解失败上下文。 */
  context_events: PerfContextEvent[];
}

export interface PerfCallTimelineResponse {
  calls: PerfSpan[];
}

/** 失败时间线行。 */
export interface PerfFailureRow {
  signal_id: string;
  /** 失败 span 关联的 fact_id，用于跳转到会话详情定位具体调用。 */
  fact_id: string;
  trace_id: string;
  span_type: string;
  span_name: string;
  tool_name: string;
  duration_ms: number;
  error: string;
  occurred_at: string;
  agent_type: string;
  conversation_ref: string;
}

export interface PerfFailuresResponse {
  failures: PerfFailureRow[];
}