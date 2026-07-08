import type { ConversationHit, ConversationMessage, ToolContext } from '../api/types';
import { ToolContextBlock } from '../components/ToolContextBlock';
import { SensitiveEvidence } from '../components/SensitiveEvidence';
import { factTypeLabel, formatFullDateTime, severityLabel } from './dashboardLabels';

function renderHighlightedText(content: string, terms: string[]) {
  const validTerms = [...new Set(terms.filter((value) => value.length >= 7 && content.includes(value)))];
  if (validTerms.length === 0) return content;
  const escaped = validTerms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const regex = new RegExp(`(${escaped.join('|')})`, 'g');
  const parts = content.split(regex).filter(Boolean);
  return parts.map((part, index) =>
    validTerms.includes(part) ? <mark key={`mark-${index}`}>{part}</mark> : part
  );
}

function roleLabel(role: string): string {
  return {
    user: '提交 Prompt',
    assistant: '响应内容',
    system: '运行环境',
    tool: '工具',
    event: '事件',
  }[role] ?? role;
}

function hitTitle(hit: ConversationHit): string {
  return factTypeLabel(hit.category || hit.fact_type);
}

function hitReadableText(hit: ConversationHit): string {
  const text = hit.content_preview || hit.summary;
  if (!text) return '该命中缺少可展示的上下文，请回到输入输出查看相邻内容。';
  return text
    .replace(/^破坏性操作[:：]\s*/, '检测到破坏性操作：')
    .replace(/^工具\s+/, '工具活动：');
}

export function MessageItem({
  message,
  highlightTerms,
}: {
  message: ConversationMessage;
  highlightTerms: string[];
}) {
  const isSystem = message.role === 'system';
  const rendered = renderHighlightedText(message.content, highlightTerms);
  if (isSystem) {
    return (
      <article className="conversation-message system-message" data-fact-id={message.fact_id}>
        <details>
          <summary>
            <strong>{roleLabel(message.role)}</strong>
            <small>{formatFullDateTime(message.occurred_at)}</small>
          </summary>
          <p>{rendered}</p>
        </details>
      </article>
    );
  }
  return (
    <article className="conversation-message" data-fact-id={message.fact_id}>
      <header>
        <strong>{roleLabel(message.role)}</strong>
        <small>{formatFullDateTime(message.occurred_at)}</small>
      </header>
      <p>{rendered}</p>
    </article>
  );
}

export function HitItem({
  hit,
  highlightTerms,
  highlighted = false,
}: {
  hit: ConversationHit;
  highlightTerms: string[];
  highlighted?: boolean;
}) {
  const className = highlighted ? 'conversation-hit conversation-hit--highlight' : 'conversation-hit';
  return (
    <article className={className} data-fact-id={hit.fact_id}>
      <header>
        <strong>{hitTitle(hit)}</strong>
        <span>{severityLabel(hit.severity)}</span>
      </header>
      <ToolContextBlock context={hit.tool_context as ToolContext | null} />
      <SensitiveEvidence matches={hit.sensitive_matches} />
      <p>{renderHighlightedText(hitReadableText(hit), highlightTerms)}</p>
      <small>{formatFullDateTime(hit.occurred_at)}</small>
    </article>
  );
}

export function isActionableHit(hit: ConversationHit): boolean {
  const category = hit.category.toLowerCase();
  if (hit.severity === 'high' || hit.severity === 'medium') return true;
  if ((hit.sensitive_matches ?? []).some((m) => m.confidence === 'high')) return true;
  return [
    'tool_execution_failure',
    'tool_execution_timeout',
    'workflow_step_failure',
    'workflow_step_timeout',
    'file_change',
    'destructive_operation',
    'sensitive_content_exposure',
  ].includes(category);
}

export function technicalHitSummary(hits: ConversationHit[]): string {
  const counts = hits.reduce<Record<string, number>>((acc, hit) => {
    const label = factTypeLabel(hit.category || hit.fact_type);
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([label, count]) => `${label} ${count} 条`)
    .join('、');
}

export function buildHighlightTerms(
  messages: ConversationMessage[],
  hits: ConversationHit[],
  highlightedHits: ConversationHit[]
): string[] {
  return [
    ...highlightedHits.flatMap((hit) => [
      hit.tool_context?.command,
      hit.tool_context?.command_excerpt,
      hit.tool_context?.error_excerpt,
    ]),
    ...messages.flatMap((m) => (m.sensitive_matches ?? []).map((match) => match.matched_value)),
    ...hits.flatMap((h) => (h.sensitive_matches ?? []).map((match) => match.matched_value)),
  ].filter((value): value is string => typeof value === 'string' && value.length >= 7);
}
