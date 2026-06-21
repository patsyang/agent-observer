import { X } from 'lucide-react';

import type { ConversationDetail, ConversationHit } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { factTypeLabel, formatDateTime, severityLabel } from './dashboardLabels';

interface Props {
  detail: ConversationDetail;
  onClose: () => void;
}

export function ConversationDrawer({ detail, onClose }: Props) {
  const actionableHits = detail.hits.filter(isActionableHit);
  const technicalHits = detail.hits.filter((hit) => !isActionableHit(hit));

  return (
    <div className="drawer-backdrop" role="presentation">
      <aside className="drawer conversation-drawer" aria-label="会话详情" data-testid="conversation-drawer">
        <header className="drawer-header">
          <div>
            <span>会话</span>
            <h2>{detail.conversation_ref}</h2>
            <p>{formatDateTime(detail.started_at)} - {formatDateTime(detail.last_event_at)}</p>
          </div>
          <button className="ghost-button" onClick={onClose} type="button" aria-label="关闭会话详情">
            <X aria-hidden="true" size={16} />
          </button>
        </header>

        <dl className="drawer-meta">
          <div>
            <dt>模型调用累计有效 token</dt>
            <dd>{formatNumber(detail.token_usage.effective_units)}</dd>
          </div>
          <div>
            <dt>模型调用</dt>
            <dd>{formatNumber(detail.token_usage.model_call_count ?? 0)} 次</dd>
          </div>
          <div>
            <dt>单次模型调用峰值</dt>
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
        </dl>

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
                  <p>{message.content}</p>
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
                      <p>{hitReadableText(hit)}</p>
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
                    {technicalHitSummary(technicalHits)}。这些记录只说明 Codex 执行过本地工具或产生了低证据事件，不代表需要处理的问题。
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
  return ['codex_error', 'command_timeout', 'tool_failure', 'high_risk_operation', 'sensitive_touch', 'sensitive_object_touch'].includes(category);
}

function hitTitle(hit: ConversationHit): string {
  return factTypeLabel(hit.category || hit.fact_type);
}

function hitReadableText(hit: ConversationHit): string {
  const text = hit.content_preview || hit.summary;
  if (!text) return '该命中缺少可展示的上下文，请回到输入输出查看相邻内容。';
  return text
    .replace(/^高风险操作[:：]\s*/, '检测到高风险操作：')
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
