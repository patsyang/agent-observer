import { RefreshCw, Search, X } from 'lucide-react';

import type {
  ConversationDetail,
  ConversationHitsResponse,
  ConversationMessagesResponse,
  HitsByFactIdsResponse,
  MessageLocateResponse,
} from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { formatDateTime } from './dashboardLabels';
import {
  HitItem,
  MessageItem,
  technicalHitSummary,
} from './ConversationDrawerItems';
import { useConversationDrawer } from './useConversationDrawer';

interface Props {
  detail: ConversationDetail;
  highlightFactIds?: string[];
  highlightTitle?: string;
  onClose: () => void;
  loadMessages: (ref: string, role?: string, page?: number) => Promise<ConversationMessagesResponse>;
  loadHits: (ref: string, category?: string, page?: number) => Promise<ConversationHitsResponse>;
  locateMessage: (ref: string, factId: string) => Promise<MessageLocateResponse>;
  loadHitsByFactIds: (ref: string, factIds: string[]) => Promise<HitsByFactIdsResponse>;
}

export function ConversationDrawer({
  detail, highlightFactIds = [], highlightTitle = '当前信号命中', onClose,
  loadMessages, loadHits, locateMessage, loadHitsByFactIds,
}: Props) {
  const drawer = useConversationDrawer({
    detail, highlightFactIds, onClose,
    loadMessages, loadHits, locateMessage, loadHitsByFactIds,
  });
  const {
    activeTab, switchTab,
    messagesTab, hitsTab,
    highlightedHits, technicalExpanded, setTechnicalExpanded,
    onMessagesFilterChange, refreshCurrentTab, loadMore,
    highlightTerms, actionableHits, technicalHits,
    searchQuery, onSearchChange, filteredMessages,
  } = drawer;

  const conversationName = detail.session_title || detail.conversation_ref;

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="drawer conversation-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="会话详情"
        data-testid="conversation-drawer"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <span>会话</span>
            <h2>{conversationName}</h2>
            <p>{formatDateTime(detail.started_at)} - {formatDateTime(detail.last_event_at)}</p>
            <small className="muted-inline" title="会话标识（排障用）">{detail.conversation_ref}</small>
          </div>
          <div className="drawer-header-actions">
            <button
              className="ghost-button"
              onClick={refreshCurrentTab}
              type="button"
              aria-label="刷新当前页"
              title="刷新当前页"
              data-testid="drawer-refresh"
            >
              <RefreshCw aria-hidden="true" size={16} />
            </button>
            <button className="ghost-button" onClick={onClose} type="button" aria-label="关闭会话详情">
              <X aria-hidden="true" size={16} />
            </button>
          </div>
        </header>

        <dl className="drawer-meta">
          <div><dt>工作区</dt><dd>{workspaceLabel(detail)}</dd></div>
          <div><dt>累计实际计算Token</dt><dd>{formatNumber(detail.token_usage.effective_units)}</dd></div>
          <div><dt>输入 token</dt><dd>{formatNumber(detail.token_usage.input_token_units ?? 0)}</dd></div>
          <div><dt>输出 token</dt><dd>{formatNumber(detail.token_usage.output_token_units ?? 0)}</dd></div>
          <div><dt>调用次数</dt><dd>{formatNumber(detail.token_usage.model_call_count ?? 0)} 次</dd></div>
          <div><dt>单次实际计算Token峰值</dt><dd>{formatNumber(detail.token_usage.max_single_call_units ?? 0)}</dd></div>
          <div><dt>缓存命中 token</dt><dd>{formatNumber(detail.token_usage.cached_input_units ?? 0)}</dd></div>
          <div><dt>缓存命中率</dt><dd>{formatPercent(detail.token_usage.cache_hit_rate)}</dd></div>
          <div><dt>Credits</dt><dd>{formatNumber(detail.token_usage.credit_total ?? 0)}</dd></div>
        </dl>

        {highlightedHits.length > 0 && (
          <section className="drawer-section">
            <h3>{highlightTitle} ({highlightedHits.length})</h3>
            <div className="conversation-hit-list">
              {highlightedHits.map((hit) => (
                <HitItem key={hit.fact_id} hit={hit} highlightTerms={highlightTerms} highlighted />
              ))}
            </div>
          </section>
        )}

        <div className="drawer-tabs" role="tablist">
          <button
            role="tab"
            aria-selected={activeTab === 'messages'}
            className={activeTab === 'messages' ? 'tab-button active' : 'tab-button'}
            onClick={() => switchTab('messages')}
            type="button"
          >
            输入输出 ({detail.messages_total})
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'hits'}
            className={activeTab === 'hits' ? 'tab-button active' : 'tab-button'}
            onClick={() => switchTab('hits')}
            type="button"
          >
            命中内容 ({detail.hits_total})
          </button>
        </div>

        <div className="drawer-search">
          <Search aria-hidden="true" size={14} />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索已加载内容（大小写不敏感）"
            aria-label="搜索已加载内容"
            data-testid="drawer-search-input"
          />
          {searchQuery && <small className="muted-inline">仅搜索已加载内容</small>}
        </div>

        {activeTab === 'messages' && (
          <section className="drawer-section" data-testid="messages-tab">
            <div className="tab-filter">
              <button className={messagesTab.filter === '' ? 'active' : ''} onClick={() => onMessagesFilterChange('')} type="button">全部</button>
              <button className={messagesTab.filter === 'user' ? 'active' : ''} onClick={() => onMessagesFilterChange('user')} type="button">User</button>
              <button className={messagesTab.filter === 'assistant' ? 'active' : ''} onClick={() => onMessagesFilterChange('assistant')} type="button">Assistant</button>
            </div>
            {messagesTab.loading && <p>正在加载...</p>}
            {messagesTab.error && <p>加载失败：{messagesTab.error}</p>}
            {!messagesTab.loading && !messagesTab.error && messagesTab.items.length === 0 && !searchQuery && (
              <p>该会话暂无可展示的输入输出原文。</p>
            )}
            {!messagesTab.loading && !messagesTab.error && filteredMessages.length === 0 && searchQuery && (
              <p>未找到匹配“{searchQuery}”的已加载内容。</p>
            )}
            <div className="conversation-message-list">
              {filteredMessages.map((m) => (
                <MessageItem key={m.fact_id} message={m} highlightTerms={highlightTerms} />
              ))}
            </div>
            {messagesTab.has_more && (
              <button className="load-more-button" onClick={loadMore} type="button" data-testid="load-more" disabled={messagesTab.loading}>
                加载更多（剩余 {messagesTab.total - messagesTab.items.length} 条）
              </button>
            )}
          </section>
        )}

        {activeTab === 'hits' && (
          <section className="drawer-section" data-testid="hits-tab">
            {hitsTab.loading && <p>正在加载...</p>}
            {hitsTab.error && <p>加载失败：{hitsTab.error}</p>}
            {!hitsTab.loading && !hitsTab.error && hitsTab.items.length === 0 && !searchQuery && (
              <p>该会话没有被信号命中的内容。</p>
            )}
            {!hitsTab.loading && !hitsTab.error && hitsTab.items.length > 0 && actionableHits.length === 0 && technicalHits.length === 0 && searchQuery && (
              <p>未找到匹配“{searchQuery}”的已加载命中。</p>
            )}
            {actionableHits.length > 0 && (
              <div className="conversation-hit-list">
                {actionableHits.map((hit) => (
                  <HitItem key={hit.fact_id} hit={hit} highlightTerms={highlightTerms} />
                ))}
              </div>
            )}
            {technicalHits.length > 0 && (
              <div className="conversation-hit-summary">
                <strong>{actionableHits.length > 0 ? '本页已折叠技术活动' : '暂无需要分析的风险或错误命中'}</strong>
                <p>
                  本页已折叠 {formatNumber(technicalHits.length)} 条低价值技术事件：
                  {technicalHitSummary(technicalHits)}。这些记录只说明 {agentLabel(detail.agent_type)} 执行过本地工具或产生了低证据事件，不代表需要处理的问题。
                </p>
                <button
                  className="ghost-button"
                  onClick={() => setTechnicalExpanded(!technicalExpanded)}
                  type="button"
                  aria-expanded={technicalExpanded}
                  data-testid="toggle-technical-hits"
                >
                  {technicalExpanded ? '收起' : '展开查看'}
                </button>
                {technicalExpanded && (
                  <div className="conversation-hit-list technical-hits-list">
                    {technicalHits.map((hit) => (
                      <HitItem key={hit.fact_id} hit={hit} highlightTerms={highlightTerms} />
                    ))}
                  </div>
                )}
              </div>
            )}
            {hitsTab.has_more && (
              <button className="load-more-button" onClick={loadMore} type="button" data-testid="load-more" disabled={hitsTab.loading}>
                加载更多（剩余 {hitsTab.total - hitsTab.items.length} 条）
              </button>
            )}
          </section>
        )}
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

function formatPercent(value?: number): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}
