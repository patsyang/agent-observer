import type { CollectorsResponse, FactsResponse, TimeWindow, UsageSummary } from '../api/types';
import { formatCount, formatNumber } from '../utils/numberFormat';

export function sourceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    online: '在线',
    degraded: '异常但进程仍在',
    offline: '离线',
    source_missing: '数据源缺失',
    source_locked: '数据源锁定',
  };
  return labels[status] ?? status;
}

export function reasonCodeLabel(reason: string): string {
  const labels: Record<string, string> = {
    run_once: '单次上报完成',
    run_once_completed: '单次上报完成',
    start_running: '持续采集中',
    started: '已启动',
    collecting: '采集中',
    uploading: '上传中',
    waiting: '等待下一轮',
    backfilling: '历史回填中',
    policy_stale: '策略待刷新',
    heartbeat_stale: '心跳已过期',
    source_locked: '数据源锁定',
    collector_offline: '采集器已停止',
    collector_stopped: '采集器已停止',
  };
  return labels[reason] ?? reason;
}

export function collectorRuntimeLabel(status: string, phase?: string): string {
  if (status === 'online') {
    const phases: Record<string, string> = {
      collecting: '在线采集中',
      uploading: '在线上传中',
      waiting: '在线等待下一轮',
      backfilling: '在线回填历史',
      starting: '在线启动中',
      idle: '在线空闲',
    };
    return phases[phase ?? ''] ?? '在线';
  }
  if (status === 'degraded') return '异常但进程仍在';
  return sourceStatusLabel(status);
}

export function factTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    collector_health: '采集器自检',
    collector_fixture: '采集器自检',
    content: 'Codex 内容',
    codex_prompt: '用户 Prompt',
    codex_message: 'Codex 消息',
    codex_reasoning: '推理片段',
    tool_execution_failure: '工具执行失败',
    tool_execution_timeout: '工具执行超时',
    workflow_step_failure: 'Workflow 失败',
    workflow_step_timeout: 'Workflow 超时',
    error: '执行异常',
    tool: '工具事件',
    tool_call: '工具调用',
    tool_result: '工具结果',
    risk: '风险命中',
    file_change: '文件变更',
    destructive_operation: '破坏性操作',
    sensitive_content_exposure: '敏感内容暴露',
    enrichment: '补证命中',
    enrichment_result: '补证结果',
    unknown: '低证据事件',
    uncategorized: '低证据事件',
  };
  return labels[type] ?? type;
}

export function qualityLabel(quality: string): string {
  const labels: Record<string, string> = {
    high: '高',
    low: '低',
    unknown: '未知',
  };
  return labels[quality] ?? quality;
}

export function localizedSummary(summary: string): string {
  if (summary.startsWith('Windows collector fixture heartbeat') && summary.endsWith('host summary')) {
    return '采集器完成一次安全自检，状态、游标和 outbox 已结构化上报。';
  }
  return summary;
}

export function severityLabel(severity: string): string {
  const labels: Record<string, string> = {
    high: '高风险',
    medium: '中风险',
    low: '低风险',
    unknown: '未知风险',
  };
  return labels[severity] ?? severity;
}

export function activityTagLabel(value: string): string {
  const labels: Record<string, string> = {
    codex_turn: 'Codex 对话',
    bug_fix: '缺陷修复',
    implementation: '实现开发',
    test_run: '测试运行',
    unknown: '未识别活动',
  };
  return labels[value] ?? value;
}

export function riskTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    file_change: '文件变更',
    destructive_operation: '破坏性操作',
    sensitive_content_exposure: '敏感内容暴露',
  };
  return labels[value] ?? value;
}

export function objectTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    configuration: '配置',
    file_path: '文件路径',
    workspace_file: '工作区文件',
    workspace: '工作区',
    command: '命令',
    auth: '认证对象',
    credential: '认证凭据对象',
  };
  return labels[value] ?? value;
}

export function scopeValueLabel(scope: string, value: string): string {
  if (!looksLikeOpaqueRef(value)) return value;
  if (scope === 'session') return '会话引用';
  if (scope === 'conversation') return '对话引用';
  return '对象引用';
}

export function looksLikeOpaqueRef(value: string): boolean {
  return /\b(ref|proj|hash|fact|codex)[-:_]/i.test(value) || /^[a-f0-9]{12,}$/i.test(value);
}

export function sumBacklog(data: CollectorsResponse): number {
  return data.collectors.reduce((total, collector) => total + collector.outbox_backlog, 0);
}

export function qualitySummary(data: FactsResponse): string {
  const high = data.facts.filter((fact) => fact.quality === 'high').length;
  const low = data.facts.filter((fact) => fact.quality === 'low').length;
  return `高置信 ${formatNumber(high)} / 待补证 ${formatNumber(low)}`;
}

export function latestFactTitle(fact: FactsResponse['facts'][number] | undefined): string {
  if (!fact) return '暂无命中';
  return factTypeLabel(fact.category || fact.fact_type);
}

export function queueSummary(activeCount: number): string {
  return activeCount > 0 ? `${formatCount(activeCount, '个信号待处理')}` : '暂无待处理信号';
}

export function emptyUsage(window: TimeWindow): UsageSummary {
  return {
    window,
    totals: {
      effective_units: 0,
      unknown_units: 0,
      cached_input_units: 0,
      input_token_units: 0,
      cache_hit_rate: 0
    },
    trend: [],
    rollups: []
  };
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '暂无心跳';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
