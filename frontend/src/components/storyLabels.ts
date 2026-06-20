import { formatNumber } from '../utils/numberFormat';
import { looksLikeOpaqueRef } from '../pages/dashboardLabels';

export function attentionStateLabel(value: string): string {
  const labels: Record<string, string> = {
    active: '待处理',
    needs_review: '需复核',
    handled_hidden: '已处理隐藏',
  };
  return labels[value] ?? value;
}

export function handlingStateLabel(value: string): string {
  const labels: Record<string, string> = {
    unread: '未读',
    read: '已读',
    handled: '已处理',
  };
  return labels[value] ?? value;
}

export function diagnosticStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    none: '暂无诊断',
    pending: '诊断排队中',
    running: '诊断执行中',
    succeeded: '诊断成功',
    failed: '诊断失败',
    expired: '诊断已过期',
    canceled: '诊断已取消',
  };
  return labels[value] ?? value;
}

export function conclusionCodeLabel(value: string): string {
  const labels: Record<string, string> = {
    known_issue: '已知问题',
    needs_fix: '需要修复',
    accepted_risk: '接受风险',
    not_actionable: '无需处理',
  };
  return labels[value] ?? value;
}

export function storyKindLabel(storyKey: string): string {
  if (storyKey.startsWith('command_timeout:')) return '命令超时';
  if (storyKey.startsWith('usage:')) return '用量异常';
  if (storyKey.startsWith('risk:sensitive_object_touch')) return '敏感对象触达';
  if (storyKey.startsWith('risk:high_risk_operation')) return '高风险操作';
  if (storyKey.startsWith('risk:')) return '风险信号';
  if (storyKey.startsWith('error:')) return '错误复发';
  return '观察故事';
}

export function usageSummaryText(summary: {
  attributed_units: number;
  associated_units: number;
  no_usage_reason: string | null;
}): string {
  if (summary.no_usage_reason) return summary.no_usage_reason;
  if (summary.attributed_units > 0) return `已归因 ${formatUnits(summary.attributed_units)}，关联 ${formatUnits(summary.associated_units)}`;
  return `仅关联 ${formatUnits(summary.associated_units)}，未做硬分摊`;
}

export function compactListSummary(items: string[], noun: string): string {
  if (items.length === 0) return `暂无${noun}`;
  const humanItems = items.filter((item) => !looksLikeOpaqueRef(item));
  if (humanItems.length > 0 && humanItems.length <= 3) return humanItems.join('、');
  if (humanItems.length > 3) return `${humanItems.slice(0, 2).join('、')} 等 ${formatNumber(humanItems.length)} 个${noun}`;
  return `${formatNumber(items.length)} 条${noun}，详情中可追溯证据引用`;
}

export function evidenceSummary(refs: string[]): string {
  if (refs.length === 0) return '暂无证据投影';
  return `${formatNumber(refs.length)} 条证据投影`;
}

export function storyEvidenceSummary(options: {
  evidence_refs: string[];
  latest_summary?: string | null;
  occurrence_count?: number;
}): string {
  if (options.latest_summary) return options.latest_summary;
  if (options.occurrence_count && options.occurrence_count > 0) return `${formatNumber(options.occurrence_count)} 条事实证据`;
  return evidenceSummary(options.evidence_refs);
}

function formatUnits(value: number): string {
  return formatNumber(value);
}
