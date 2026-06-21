import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Search } from 'lucide-react';

import type { ConversationDetail, ConversationSummary, ConversationsResponse, ConversationTimeWindow } from '../api/types';
import { ConversationDrawer } from './ConversationDrawer';
import { ConversationTable } from './ConversationTable';
import { TimeRangePicker } from './TimeRangePicker';

type Filters = {
  window: ConversationTimeWindow | '';
  start_at: string;
  end_at: string;
  prompt_query: string;
  response_query: string;
  page: number;
  page_size: number;
};

const PAGE_SIZE = 50;
const windowOptions: Array<{ value: ConversationTimeWindow; label: string }> = [
  { value: '1h', label: '1小时' },
  { value: '2h', label: '2小时' },
  { value: '3h', label: '3小时' },
  { value: '24h', label: '24小时' },
  { value: 'today', label: '今天' },
];

export function ConversationQueryPage({
  initialFactId,
  loadConversationDetail,
  loadConversationForFact,
  loadConversations,
  onBack,
  backLabel = '返回',
}: {
  initialFactId?: string | null;
  loadConversationDetail: (conversationRef: string) => Promise<ConversationDetail>;
  loadConversationForFact: (factId: string) => Promise<ConversationDetail>;
  loadConversations: (filters: Filters) => Promise<ConversationsResponse>;
  onBack?: () => void;
  backLabel?: string;
}) {
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [draftFilters, setDraftFilters] = useState<Pick<Filters, 'window' | 'start_at' | 'end_at' | 'prompt_query' | 'response_query'>>(defaultFilters);
  const [rows, setRows] = useState<ConversationSummary[]>([]);
  const [meta, setMeta] = useState({ total: 0, page: 1, page_size: PAGE_SIZE, has_more: false });
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [detailState, setDetailState] = useState<'idle' | 'loading' | 'error'>('idle');

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    loadConversations(filters)
      .then((data) => {
        if (cancelled) return;
        setRows(data.conversations);
        setMeta({ total: data.total, page: data.page, page_size: data.page_size, has_more: data.has_more });
        setState(data.conversations.length ? 'ready' : 'empty');
      })
      .catch(() => {
        if (!cancelled) setState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [filters, loadConversations]);

  const openConversation = useCallback((conversationRef: string) => {
    setDetailState('loading');
    loadConversationDetail(conversationRef)
      .then((data) => {
        setDetail(data);
        setDetailState('idle');
      })
      .catch(() => setDetailState('error'));
  }, [loadConversationDetail]);

  useEffect(() => {
    if (!initialFactId) return;
    setDetailState('loading');
    loadConversationForFact(initialFactId)
      .then((data) => {
        setDetail(data);
        setDetailState('idle');
      })
      .catch(() => setDetailState('error'));
  }, [initialFactId, loadConversationForFact]);

  const updateFilters = (patch: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...patch, page: 1 }));
  };

  const updateDraftFilters = (patch: Partial<Filters>) => {
    setDraftFilters((current) => ({ ...current, ...patch }));
  };

  const submitSearch = () => {
    updateFilters({
      window: draftFilters.window,
      start_at: draftFilters.start_at,
      end_at: draftFilters.end_at,
      prompt_query: draftFilters.prompt_query.trim(),
      response_query: draftFilters.response_query.trim(),
    });
  };

  return (
    <section className="panel conversation-page" data-testid="conversation-page">
      {onBack && (
        <div className="page-actions">
          <button className="compact-button" onClick={onBack} type="button">
            <ArrowLeft aria-hidden="true" size={14} />
            {backLabel}
          </button>
        </div>
      )}

      <div className="conversation-toolbar" aria-label="会话筛选">
        <TextFilter
          testId="prompt-query"
          label="提交 Prompt"
          onChange={(prompt_query) => updateDraftFilters({ prompt_query })}
          onSubmit={submitSearch}
          value={draftFilters.prompt_query}
        />
        <TextFilter
          testId="response-query"
          label="响应内容"
          onChange={(response_query) => updateDraftFilters({ response_query })}
          onSubmit={submitSearch}
          value={draftFilters.response_query}
        />
        <div className="conversation-time-group">
          <span className="conversation-field-label">时间</span>
          <TimeRangePicker
            end={draftFilters.end_at}
            onApply={({ window, start_at, end_at }) => updateDraftFilters({ window, start_at, end_at })}
            options={windowOptions}
            start={draftFilters.start_at}
            window={draftFilters.window}
          />
        </div>
        <button
          aria-label="搜索会话"
          className="icon-button conversation-search-button"
          data-testid="conversation-search"
          onClick={submitSearch}
          title="搜索会话"
          type="button"
        >
          <Search aria-hidden="true" size={16} />
        </button>
      </div>

      {state === 'loading' && <p>正在加载会话</p>}
      {state === 'error' && <p>会话查询不可用，请确认后端服务正在运行。</p>}
      {state === 'empty' && <p>当前筛选没有会话。默认时间范围为最近 1 小时，可放宽时间或关键字。</p>}
      {state === 'ready' && (
        <ConversationTable
          meta={meta}
          onOpen={openConversation}
          onPage={(page) => setFilters((current) => ({ ...current, page }))}
          rows={rows}
        />
      )}
      {detailState === 'loading' && <p className="result-note">正在加载会话详情</p>}
      {detailState === 'error' && <p className="result-note">会话详情不可用。</p>}
      {detail && <ConversationDrawer detail={detail} onClose={() => setDetail(null)} />}
    </section>
  );
}

const defaultFilters: Filters = {
  window: '1h',
  start_at: '',
  end_at: '',
  prompt_query: '',
  response_query: '',
  page: 1,
  page_size: PAGE_SIZE,
};

function TextFilter({
  label,
  onChange,
  onSubmit,
  testId,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  testId: string;
  value: string;
}) {
  return (
    <label className="conversation-inline-field">
      {label}
      <input
        data-testid={testId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder="关键字模糊搜索"
      />
    </label>
  );
}
