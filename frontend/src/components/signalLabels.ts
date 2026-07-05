import { formatNumber } from '../utils/numberFormat';

export function decisionStateLabel(value: string): string {
  const labels: Record<string, string> = {
    unread: '未读',
    read: '已读',
    needs_review: '需复核',
    handled: '已处理'
  };
  return labels[value] ?? value;
}

export function enrichmentStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    none: '暂无补证',
    pending: '补证排队中',
    queued: '补证排队中',
    running: '补证执行中',
    succeeded: '补证成功',
    failed: '补证失败',
    expired: '补证已过期',
    canceled: '补证已取消',
    cancelled: '补证已取消'
  };
  return labels[value] ?? value;
}

export function conclusionCodeLabel(value: string): string {
  const labels: Record<string, string> = {
    known_issue: '已知问题',
    needs_fix: '需要修复',
    accepted_risk: '接受风险',
    expected_nonzero_exit: '期望非零退出',
    duplicate_signal: '重复信号',
    not_actionable: '无需处理'
  };
  return labels[value] ?? value;
}

export function signalKindLabel(value: string): string {
  const labels: Record<string, string> = {
    tool_execution_failure: '工具失败',
    tool_execution_timeout: '工具超时',
    workflow_step_failure: 'Workflow 失败',
    workflow_step_timeout: 'Workflow 超时',
    change_volume_anomaly: '变更量异常',
    key_file_change: '关键文件',
    destructive_operation_attempt: '破坏性操作',
    sensitive_content_exposure: '敏感内容',
    workflow_gate_blocked: '工作门禁阻断',
    validation_failure: '校验失败',
    repeated_tool_failure: '重复工具失败',
    agent_loop_stuck: 'Agent卡循环',
    usage_spike: '用量激增',
    low_cache_hit_rate: '缓存命中率低',
    unknown_usage_dominant: '未知活动主导'
  };
  return labels[value] ?? '未知信号';
}

export function riskFamilyLabel(value: string): string {
  const labels: Record<string, string> = {
    data_exposure: '数据泄露',
    behavior_anomaly: '行为异常',
    execution_error: '执行错误',
    usage_cost: '用量成本',
    uncategorized: '未归类'
  };
  return labels[value] ?? value;
}

export function usageSummaryText(summary: {
  effective_units: number;
  cached_units?: number;
  cache_hit_rate?: number | null;
  no_usage_reason: string | null;
}): string {
  if (summary.no_usage_reason) return summary.no_usage_reason;
  const cached = summary.cached_units ? `，缓存命中 ${formatNumber(summary.cached_units)}` : '';
  const rate = typeof summary.cache_hit_rate === 'number' ? `，命中率 ${(summary.cache_hit_rate * 100).toFixed(1)}%` : '';
  return `实际计算 token ${formatNumber(summary.effective_units)}${cached}${rate}`;
}

export function scopeText(scope: Record<string, unknown>): string {
  const parts = [
    ['会话', scope.conversation_count],
    ['对象', scope.object_count],
    ['失败', scope.failure_count],
    ['操作', scope.operation_count],
    ['文件', scope.file_count],
    ['超时', scope.timeout_count]
  ]
    .filter(([, value]) => typeof value === 'number' && value > 0)
    .map(([label, value]) => `${label} ${formatNumber(Number(value))}`);
  return parts.length ? parts.join(' / ') : '范围待确认';
}

export function sensitiveCategoryLabel(category: string): string {
  const labels: Record<string, string> = {
    phone: '手机号',
    email: '邮箱',
    id_card: '身份证号',
    bank_card: '银行卡号',
    token: '令牌',
    secret: '密钥',
    cookie: 'Cookie',
  };
  return labels[category] ?? category;
}
