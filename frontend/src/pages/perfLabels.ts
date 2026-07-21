/** 性能观测 - 错误解释与状态分类工具。

集中管理 task/span error 的可读化翻译和"中断 vs 失败"的状态区分，
让 PerformanceTaskDetail / PerformanceFailures / PerformanceTaskList 共享同一套语义。
 */

/** 把后端 error 原文翻译成可读中文解释。

后端 error 字段直接来自采集器（如 codex turn_aborted.reason），
用户看到英文词无法理解，这里统一翻译。未识别的 error 原样返回。
 */
export function explainTaskError(error: string): string {
  if (!error) return '';
  const map: Record<string, string> = {
    interrupted: '用户中断（任务未完成）',
    cancelled: '用户取消',
    timeout: '超时',
    rate_limit: '触发速率限制',
    auth_error: '认证失败',
    model_error: '模型返回错误',
    tool_error: '工具调用失败',
    network_error: '网络错误',
  };
  return map[error] ?? error;
}

/** 判断 error 是否属于"用户主动中断"而非系统失败。

中断类 error 不代表系统出问题，只是用户按了停止。在状态标签上区分展示，
避免用户把"用户中断"误判为"系统失败"。
 */
export function isInterruptError(error: string): boolean {
  if (!error) return false;
  return error === 'interrupted' || error === 'cancelled';
}

/** 任务/span 状态的可读标签。

优先识别中断类 error，再走通用 status 映射。
 */
export function perfStatusLabel(status: string, error?: string): string {
  if (status === 'error' && error && isInterruptError(error)) return '已中断';
  if (status === 'error') return '失败';
  if (status === 'ok') return '成功';
  return '未知';
}

/** 状态标签的 CSS class，区分中断（灰橙）与失败（红）。

中断不是真正的失败，视觉上应该弱化；只有真正的失败才用强警示色。
 */
export function perfStatusBadgeClass(status: string, error?: string): string {
  if (status === 'error' && error && isInterruptError(error)) return 'badge gray';
  if (status === 'error') return 'badge amber';
  if (status === 'ok') return 'badge green';
  return 'badge gray';
}

/** context_event 的 fact_type/category 可读标签。 */
export function contextEventLabel(event: { fact_type: string; category: string }): string {
  if (event.fact_type === 'risk') {
    if (event.category === 'file_change') return '文件变更';
    if (event.category === 'destructive_operation') return '破坏性操作';
    return '风险事件';
  }
  if (event.fact_type === 'error') {
    if (event.category === 'tool_execution_failure') return '工具执行失败';
    return '错误事件';
  }
  return event.category || event.fact_type || '事件';
}
