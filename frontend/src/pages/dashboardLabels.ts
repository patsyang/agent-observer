export function sourceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    online: '在线',
    offline: '离线',
    source_missing: '数据源缺失',
    source_locked: '数据源锁定',
    state_corrupt: '状态损坏',
    outbox_backlog: '待传队列',
    policy_not_fetched: '未拉取策略',
  };
  return labels[status] ?? status;
}

export function reasonCodeLabel(reason: string): string {
  const labels: Record<string, string> = {
    run_once: '单次上报完成',
    run_once_completed: '单次上报完成',
    start_running: '持续采集中',
    heartbeat_stale: '心跳已过期',
    policy_not_fetched: '未拉取策略',
    source_locked: '数据源锁定',
    collector_offline: '采集器已停止',
    collector_stopped: '采集器已停止',
  };
  return labels[reason] ?? reason;
}

export function factTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    collector_health: '采集器自检',
    collector_fixture: '采集器自检',
    content: 'Codex 内容',
    codex_prompt: '用户 Prompt',
    codex_message: 'Codex 消息',
    codex_reasoning: '推理片段',
    codex_error: 'Codex 错误',
    error: 'Codex 错误',
    tool: '工具事件',
    tool_call: '工具调用',
    tool_failure: '工具失败',
    tool_result: '工具结果',
    usage: '用量事实',
    risk: '风险事实',
    high_risk_operation: '高风险操作',
    sensitive_touch: '敏感触达',
    sensitive_object_touch: '敏感触达',
    diagnostic: '诊断事实',
    diagnostic_result: '补证结果',
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
    return '采集器完成一次安全白名单自检，状态、游标和 outbox 已结构化上报。';
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

export function usageKindLabel(kind: string): string {
  return kind === 'attributed' ? '已归因' : '关联';
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
    high_risk_operation: '高风险操作',
    sensitive_object_touch: '敏感对象触达',
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

function looksLikeOpaqueRef(value: string): boolean {
  return /\b(ref|proj|hash|fact|codex)[-:_]/i.test(value) || /^[a-f0-9]{12,}$/i.test(value);
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
