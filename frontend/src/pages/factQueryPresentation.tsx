import type { ReactNode } from 'react';

import type { FactQuality, ObservedFact } from '../api/types';

export function prioritizeFacts(facts: ObservedFact[]): ObservedFact[] {
  return [...facts].sort((left, right) => {
    const priorityDiff = factPriority(right) - factPriority(left);
    if (priorityDiff !== 0) return priorityDiff;
    return new Date(right.occurred_at).getTime() - new Date(left.occurred_at).getTime();
  });
}

export function qualityText(quality: FactQuality): string {
  const labels: Record<FactQuality, string> = {
    high: '高可信',
    low: '待补证',
    unknown: '未知',
  };
  return labels[quality];
}

export function factSourceLabel(fact: ObservedFact): string {
  if (fact.source_label?.startsWith('采集器 ')) return '本机';
  return fact.source_label || sourceText(fact.source);
}

export function sourceText(source: string): string {
  if (source === 'codex') return 'Codex 会话';
  return source;
}

export function eventTypeText(value?: string): string {
  const labels: Record<string, string> = {
    message: '消息事件',
    user_message: '用户消息',
    agent_message: '模型消息',
    reasoning: '推理事件',
    function_call: '工具调用',
    function_call_output: '工具结果',
    tool_result: '工具结果',
    usage_summary: '用量汇总',
    diagnostic_result: '补证结果',
    unknown: '未知事件',
  };
  return labels[value || 'unknown'] ?? value ?? '未知事件';
}

export function rawStatusText(fact: Pick<ObservedFact, 'raw_available' | 'raw_status'>): string {
  if (fact.raw_available) return '已上传原文，可直接排查';
  if (fact.raw_status === '无证据投影') return '本条没有证据投影';
  return '未上传原文，可查看摘要和字段';
}

export function shortHash(value: string): string {
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-6)}` : value;
}

export function objectTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    credential: '认证凭据对象',
    auth: '认证对象',
    configuration: '配置对象',
    file_path: '文件路径',
    workspace_file: '工作区文件',
    workspace: '工作区',
    command: '命令',
  };
  return labels[value] ?? value;
}

export function highlightSensitiveTerms(value: string): ReactNode {
  const pattern =
    /(\b(?:access|refresh|api|bearer|auth|session|credential|secret)[-_ ]?token\b|\btoken[-_ ]?(?:secret|key|value)\b|["']?token["']?\s*[:=]|\b(?:set-cookie|cookies?|cookie_jar|secret|secrets|client_secret|credential|credentials|auth|authentication|authorization)\b|auth[._/-])/gi;
  const parts = value.split(pattern);
  return parts.map((part, index) =>
    matchesSensitiveHighlight(part) ? <mark className="sensitive-hit" key={`${part}-${index}`}>{part}</mark> : part
  );
}

function factPriority(fact: ObservedFact): number {
  const category = fact.category || '';
  if (category === 'codex_prompt') return 100;
  if (category === 'codex_message') return 90;
  if (category === 'codex_reasoning') return 80;
  if (fact.fact_type === 'error' || category.includes('error')) return 70;
  if (fact.fact_type === 'risk' || category.includes('risk')) return 60;
  if (fact.quality === 'low') return 50;
  if (fact.fact_type === 'tool') return 40;
  if (fact.fact_type === 'usage') return 30;
  return 10;
}

function matchesSensitiveHighlight(value: string): boolean {
  return /^(?:\b(?:access|refresh|api|bearer|auth|session|credential|secret)[-_ ]?token\b|\btoken[-_ ]?(?:secret|key|value)\b|["']?token["']?\s*[:=]|\b(?:set-cookie|cookies?|cookie_jar|secret|secrets|client_secret|credential|credentials|auth|authentication|authorization)\b|auth[._/-])$/i.test(value);
}
