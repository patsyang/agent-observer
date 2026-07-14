import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  ConversationDetail,
  ConversationHit,
  ConversationMessage,
  ConversationHitsResponse,
  ConversationMessagesResponse,
  HitsByFactIdsResponse,
  MessageLocateResponse,
} from '../api/types';
import {
  buildHighlightTerms,
  filterHits,
  filterMessages,
  isActionableHit,
} from './ConversationDrawerItems';

export type MessagesFilter = '' | 'user' | 'assistant';
export type HitsFilter = '';

export interface TabState<T, F> {
  filter: F;
  items: T[];
  page: number;
  total: number;
  has_more: boolean;
  loaded: boolean;
  loading: boolean;
  error: string | null;
}

export const emptyMessagesTab: TabState<ConversationMessage, MessagesFilter> = {
  filter: '', items: [], page: 1, total: 0, has_more: false, loaded: false, loading: false, error: null,
};
export const emptyHitsTab: TabState<ConversationHit, HitsFilter> = {
  filter: '', items: [], page: 1, total: 0, has_more: false, loaded: false, loading: false, error: null,
};

export interface UseConversationDrawerParams {
  detail: ConversationDetail;
  highlightFactIds?: string[];
  onClose: () => void;
  loadMessages: (ref: string, role?: string, page?: number) => Promise<ConversationMessagesResponse>;
  loadHits: (ref: string, category?: string, page?: number) => Promise<ConversationHitsResponse>;
  locateMessage: (ref: string, factId: string) => Promise<MessageLocateResponse>;
  loadHitsByFactIds: (ref: string, factIds: string[]) => Promise<HitsByFactIdsResponse>;
}

export interface UseConversationDrawerReturn {
  activeTab: 'messages' | 'hits';
  switchTab: (tab: 'messages' | 'hits') => void;
  messagesTab: TabState<ConversationMessage, MessagesFilter>;
  hitsTab: TabState<ConversationHit, HitsFilter>;
  highlightedHits: ConversationHit[];
  technicalExpanded: boolean;
  setTechnicalExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  onMessagesFilterChange: (filter: MessagesFilter) => void;
  refreshCurrentTab: () => void;
  loadMore: () => void;
  highlightTerms: string[];
  actionableHits: ConversationHit[];
  technicalHits: ConversationHit[];
  searchQuery: string;
  onSearchChange: (query: string) => void;
  filteredMessages: ConversationMessage[];
}

export function useConversationDrawer({
  detail,
  highlightFactIds = [],
  onClose,
  loadMessages,
  loadHits,
  locateMessage,
  loadHitsByFactIds,
}: UseConversationDrawerParams): UseConversationDrawerReturn {
  const [activeTab, setActiveTab] = useState<'messages' | 'hits'>('messages');
  const [messagesTab, setMessagesTab] = useState<TabState<ConversationMessage, MessagesFilter>>(emptyMessagesTab);
  const [hitsTab, setHitsTab] = useState<TabState<ConversationHit, HitsFilter>>(emptyHitsTab);
  const [highlightedHits, setHighlightedHits] = useState<ConversationHit[]>([]);
  const [technicalExpanded, setTechnicalExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const ref = detail.conversation_ref;
  const focusFactId = detail.focus_fact_id;
  const highlightIds = highlightFactIds;

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // 1. 初次打开：批量查询 highlightedHits
  useEffect(() => {
    if (highlightIds.length === 0) return;
    let cancelled = false;
    loadHitsByFactIds(ref, highlightIds).then((res) => {
      if (!cancelled) setHighlightedHits(res.hits);
    }).catch(() => { /* 静默：高亮缺失不阻塞 */ });
    return () => { cancelled = true; };
  }, [ref, highlightIds, loadHitsByFactIds]);

  const loadMessagesTab = useCallback(async (filter: MessagesFilter = messagesTab.filter, page: number = 1) => {
    setMessagesTab((s) => ({ ...s, loading: true, error: null }));
    try {
      const role = filter || undefined;
      const res = await loadMessages(ref, role, page);
      setMessagesTab((s) => ({
        filter, items: page === 1 ? res.messages : [...s.items, ...res.messages],
        page: res.page, total: res.total, has_more: res.has_more,
        loaded: true, loading: false, error: null,
      }));
    } catch (e) {
      setMessagesTab((s) => ({ ...s, loading: false, error: String(e) }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, loadMessages, messagesTab.filter]);

  const loadHitsTab = useCallback(async (filter: HitsFilter = hitsTab.filter, page: number = 1) => {
    setHitsTab((s) => ({ ...s, loading: true, error: null }));
    try {
      const category = filter || undefined;
      const res = await loadHits(ref, category, page);
      setHitsTab((s) => ({
        filter, items: page === 1 ? res.hits : [...s.items, ...res.hits],
        page: res.page, total: res.total, has_more: res.has_more,
        loaded: true, loading: false, error: null,
      }));
    } catch (e) {
      setHitsTab((s) => ({ ...s, loading: false, error: String(e) }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, loadHits, hitsTab.filter]);

  // 2. 初次打开 + focus_fact_id：定位目标页，加载该页
  const focusLoadedRef = useRef(false);
  useEffect(() => {
    if (focusLoadedRef.current || !focusFactId) return;
    focusLoadedRef.current = true;
    let cancelled = false;
    let scrollTimer: ReturnType<typeof setTimeout> | undefined;
    locateMessage(ref, focusFactId).then((loc) => {
      if (cancelled) return;
      return loadMessages(ref, undefined, loc.page).then((res) => {
        if (cancelled) return;
        setMessagesTab({
          filter: '', items: res.messages, page: loc.page, total: res.total,
          has_more: res.has_more, loaded: true, loading: false, error: null,
        });
        scrollTimer = setTimeout(() => {
          const el = document.querySelector<HTMLElement>(
            `[data-fact-id="${CSS.escape(focusFactId as string)}"]`
          );
          el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }, 100);
      });
    }).catch(() => { loadMessagesTab(); });
    return () => {
      cancelled = true;
      if (scrollTimer) clearTimeout(scrollTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, focusFactId]);

  // 3. Tab 切换按需加载
  useEffect(() => {
    if (activeTab === 'messages' && !messagesTab.loaded && !focusFactId && !messagesTab.loading) {
      loadMessagesTab();
    } else if (activeTab === 'hits' && !hitsTab.loaded && !hitsTab.loading) {
      loadHitsTab();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const switchTab = (tab: 'messages' | 'hits') => {
    if (tab !== activeTab) setActiveTab(tab);
  };

  const onMessagesFilterChange = (filter: MessagesFilter) => {
    if (filter === messagesTab.filter) return;
    setMessagesTab({ ...emptyMessagesTab, filter, loading: true });
    loadMessagesTab(filter, 1);
  };

  const refreshCurrentTab = () => {
    if (activeTab === 'messages') {
      setMessagesTab({ ...emptyMessagesTab, filter: messagesTab.filter, loading: true });
      loadMessagesTab(messagesTab.filter, 1);
    } else {
      setHitsTab({ ...emptyHitsTab, filter: hitsTab.filter, loading: true });
      loadHitsTab(hitsTab.filter, 1);
    }
  };

  const loadMore = () => {
    if (activeTab === 'messages' && messagesTab.has_more && !messagesTab.loading) {
      loadMessagesTab(messagesTab.filter, messagesTab.page + 1);
    } else if (activeTab === 'hits' && hitsTab.has_more && !hitsTab.loading) {
      loadHitsTab(hitsTab.filter, hitsTab.page + 1);
    }
  };

  const allHitsForTerms = [...highlightedHits, ...hitsTab.items];
  const highlightTerms = buildHighlightTerms(messagesTab.items, allHitsForTerms, highlightedHits);
  const filteredMessages = filterMessages(messagesTab.items, searchQuery);
  const filteredRemainingHits = filterHits(
    hitsTab.items.filter((h) => !highlightIds.includes(h.fact_id)),
    searchQuery,
  );
  const actionableHits = filteredRemainingHits.filter(isActionableHit);
  const technicalHits = filteredRemainingHits.filter((h) => !isActionableHit(h));

  return {
    activeTab,
    switchTab,
    messagesTab,
    hitsTab,
    highlightedHits,
    technicalExpanded,
    setTechnicalExpanded,
    onMessagesFilterChange,
    refreshCurrentTab,
    loadMore,
    highlightTerms,
    actionableHits,
    technicalHits,
    searchQuery,
    onSearchChange: setSearchQuery,
    filteredMessages,
  };
}
