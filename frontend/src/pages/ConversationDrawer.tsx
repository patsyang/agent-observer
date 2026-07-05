import { X } from 'lucide-react';

import type { ConversationDetail, ConversationHit } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { ToolContextBlock } from '../components/ToolContextBlock';
import { SensitiveEvidence } from '../components/SensitiveEvidence';
import { factTypeLabel, formatDateTime, severityLabel } from './dashboardLabels';

interface Props {
  detail: ConversationDetail;
  highlightFactIds?: string[];
  highlightTitle?: string;
  onClose: () => void;
}

export function ConversationDrawer({ detail, highlightFactIds = [], highlightTitle = '当前信号命中', onClose }: Props) {
  const highlighted = new Set(highlightFactIds);
  const highlightedHits = detail.hits.filter((hit) => highlighted.has(hit.fact_id));
  const remainingHits = detail.hits.filter((hit) => !highlighted.has(hit.fact_id));
  const actionableHits = remainingHits.filter(isActionableHit);
  const technicalHits = remainingHits.filter((hit) => !isActionableHit(hit));
  const conversationName = detail.session_title || detail.session_ref || detail.conversation_ref;
  const highlightTerms = [
    ...highlightedHits.flatMap((hit) => [
      hit.tool_context?.command,
      hit.tool_context?.command_excerpt,
      hit.tool_context?.error_excerpt,
    ]),
    ...detail.messages.flatMap((m) => (m.sensitive_matches ?? []).map((match) => match.matched_value)),
    ...detail.hits.flatMap((h) => (h.sensitive_matches ?? []).map((match) => match.matched_value)),
  ].filter((value): value is string => typeof value === 'string' && value.length >= 7);

  return (
    <div className="drawer-backdrop" role="presentation">
      <aside className="drawer conversation-drawer" role="dialog" aria-modal="true" aria-label="会话详情" data-testid="conversation-drawer">
        <header className="drawer-header">
          <div>
            <span>会话</span>
            <h2>{conversationName}</h2>
            <p>{formatDateTime(detail.started_at)} - {formatDateTime(detail.last_event_at)}</p>
            {conversationName !== detail.conversation_ref && <small>{detail.conversation_ref}</small>}
          </div>
          <button className="ghost-button" onClick={onClose} type="button" aria-label="关闭会话详情">
            <X aria-hidden="true" size={16} />
          </button>
        </header>

        <dl className="drawer-meta">
          <div>
            <dt>工作区</dt>
            <dd>{workspaceLabel(detail)}</dd>
          </div>
          <div>
            <dt>累计实际计算Token</dt>
            <dd>{formatNumber(detail.token_usage.effective_units)}</dd>
          </div>
          <div>
            <dt>输入 token</dt>
            <dd>{formatNumber(detail.token_usage.input_token_units ?? 0)}</dd>
          </div>
          <div>
            <dt>输出 token</dt>
            <dd>{formatNumber(detail.token_usage.output_token_units ?? 0)}</dd>
          </div>
          <div>
            <dt>调用次数</dt>
            <dd>{formatNumber(detail.token_usage.model_call_count ?? 0)} 次</dd>
          </div>
          <div>
            <dt>单次实际计算Token峰值</dt>
            <dd>{formatNumber(detail.token_usage.max_single_call_units ?? 0)}</dd>
          </div>
          <div>
            <dt>缓存命中 token</dt>
            <dd>{formatNumber(detail.token_usage.cached_input_units ?? 0)}</dd>
          </div>
          <div>
            <dt>缓存命中率</dt>
            <dd>{formatPercent(detail.token_usage.cache_hit_rate)}</dd>
          </div>
          <div>
            <dt>Credits</dt>
            <dd>{formatNumber(detail.token_usage.credit_total ?? 0)}</dd>
          </div>
        </dl>

        {highlightedHits.length > 0 && (
          <section className="drawer-section">
            <h3>{highlightTitle}</h3>
            <div className="conversation-hit-list">
              {highlightedHits.map((hit) => (
                <article className="conversation-hit conversation-hit--highlight" key={hit.fact_id}>
                  <header>
                    <strong>{hitTitle(hit)}</strong>
                    <span>{severityLabel(hit.severity)}</span>
                  </header>
                  <ToolContextBlock context={hit.tool_context} />
                  <SensitiveEvidence matches={hit.sensitive_matches} />
                  <p>{renderHighlightedText(hitReadableText(hit), highlightTerms)}</p>
                  <small>{formatDateTime(hit.occurred_at)}</small>
                </article>
              ))}
            </div>
          </section>
        )}

        <section className="drawer-section">
          <h3>工作区归属</h3>
          <div className="conversation-hit-summary">
            <strong>{workspaceLabel(detail)}</strong>
            <p>{detail.workspace.workspace_path || '未识别工作区路径'}</p>
          </div>
        </section>

        <section className="drawer-section">
          <h3>输入输出</h3>
          {detail.messages.length === 0 ? (
            <p>该会话暂无可展示的输入输出原文。</p>
          ) : (
            <div className="conversation-message-list">
              {detail.messages.map((message) => (
                <article className="conversation-message" key={message.fact_id}>
                  <header>
                    <strong>{roleLabel(message.role)}</strong>
                    <small>{formatDateTime(message.occurred_at)}</small>
                  </header>
                  <p>{renderHighlightedText(message.content, highlightTerms)}</p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="drawer-section">
          <h3>命中内容</h3>
          {detail.hits.length === 0 ? (
            <p>该会话没有被信号命中的内容。</p>
          ) : (
            <>
              {actionableHits.length > 0 && (
                <div className="conversation-hit-list">
                  {actionableHits.map((hit) => (
                    <article className="conversation-hit" key={hit.fact_id}>
                      <header>
                        <strong>{hitTitle(hit)}</strong>
                        <span>{severityLabel(hit.severity)}</span>
                      </header>
                      <ToolContextBlock context={hit.tool_context} />
                      <SensitiveEvidence matches={hit.sensitive_matches} />
                      <p>{renderHighlightedText(hitReadableText(hit), highlightTerms)}</p>
                      <small>{formatDateTime(hit.occurred_at)}</small>
                    </article>
                  ))}
                </div>
              )}
              {technicalHits.length > 0 && (
                <div className="conversation-hit-summary">
                  <strong>{actionableHits.length > 0 ? '其他技术活动已折叠' : '暂无需要分析的风险或错误命中'}</strong>
                  <p>
                    已折叠 {formatNumber(technicalHits.length)} 条低价值技术事件：
                    {technicalHitSummary(technicalHits)}。这些记录只说明 {agentLabel(detail.agent_type)} 执行过本地工具或产生了低证据事件，不代表需要处理的问题。
                  </p>
                </div>
              )}
            </>
          )}
        </section>
      </aside>
    </div>
  );
}

function workspaceLabel(detail: ConversationDetail): string {
  return detail.workspace.workspace_label || basename(detail.workspace.workspace_path) || '工作区未知';
}

function agentLabel(agentType: string): string {
  if (agentType === 'claude') return 'Claude Code';
  if (agentType === 'codex') return 'Codex';
  if (agentType === 'workbuddy') return 'WorkBuddy';
  return 'Agent';
}

function basename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.at(-1) ?? '';
}

function roleLabel(role: string): string {
  return {
    user: '提交 Prompt',
    assistant: '响应内容',
    system: '系统',
    tool: '工具',
    event: '事件',
  }[role] ?? role;
}

function formatPercent(value?: number): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}

function isActionableHit(hit: ConversationHit): boolean {
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
    'sensitive_content_exposure'
  ].includes(category);
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

function technicalHitSummary(hits: ConversationHit[]): string {
  const counts = hits.reduce<Record<string, number>>((acc, hit) => {
    const label = factTypeLabel(hit.category || hit.fact_type);
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([label, count]) => `${label} ${formatNumber(count)} 条`)
    .join('、');
}

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
