import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';

import type { FactDetail, FactQuality, FactsResponse, ObservedFact, TimeWindow } from '../api/types';
import { TimeWindowTabs } from '../components/TimeWindowTabs';
import { formatNumber } from '../utils/numberFormat';
import { EmptyDetailPanel, FactDetailPanel } from './FactDetailPanel';
import { FactTable } from './FactTable';
import { formatDateTime } from './dashboardLabels';
import { prioritizeFacts } from './factQueryPresentation';

export type InitialFactFilters = Partial<Pick<Filters, 'fact_type' | 'include_health' | 'quality' | 'source' | 'window'>>;

type Filters = {
  quality: FactQuality | 'all';
  fact_type: string;
  source: string;
  window: TimeWindow;
  include_health: boolean;
  limit: number;
  offset: number;
};

const PAGE_SIZE = 50;

export function FactQueryPage({
  initialFactFilters,
  initialFactId,
  loadFacts,
  loadFactDetail
}: {
  initialFactFilters?: InitialFactFilters | null;
  initialFactId?: string | null;
  loadFacts: (filters: Filters) => Promise<FactsResponse>;
  loadFactDetail: (factId: string) => Promise<FactDetail>;
}) {
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [facts, setFacts] = useState<ObservedFact[]>([]);
  const [meta, setMeta] = useState({ total: 0, limit: PAGE_SIZE, offset: 0 });
  const [detail, setDetail] = useState<FactDetail | null>(null);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const detailRef = useRef<HTMLElement | null>(null);
  const loadedInitialFactRef = useRef<string | null>(null);

  useEffect(() => {
    if (!initialFactFilters) return;
    setFilters((current) => ({
      ...current,
      ...initialFactFilters,
      include_health: initialFactFilters.include_health ?? current.include_health,
      limit: PAGE_SIZE,
      offset: 0,
    }));
  }, [initialFactFilters]);

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    loadFacts(filters)
      .then((data) => {
        if (cancelled) return;
        setFacts(data.facts);
        setMeta({
          total: data.total ?? data.facts.length,
          limit: data.limit ?? filters.limit,
          offset: data.offset ?? filters.offset,
        });
        setState(data.facts.length ? 'ready' : 'empty');
        setLastRefresh(new Date().toISOString());
      })
      .catch(() => {
        if (!cancelled) setState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [filters, loadFacts, refreshToken]);

  const inspect = useCallback((factId: string) => {
    loadFactDetail(factId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [loadFactDetail]);

  useEffect(() => {
    if (!initialFactId || loadedInitialFactRef.current === initialFactId) return;
    loadedInitialFactRef.current = initialFactId;
    inspect(initialFactId);
  }, [initialFactId, inspect]);

  const updateFilters = (patch: Partial<Filters>) => {
    setDetail(null);
    setFilters((current) => ({ ...current, ...patch, offset: 0 }));
  };
  const refresh = () => {
    setRefreshToken((value) => value + 1);
    if (detail) inspect(detail.fact.fact_id);
  };
  const visibleFacts = prioritizeFacts(facts);
  const selectedFactId = detail?.fact.fact_id ?? null;
  const selectedIndex = selectedFactId ? visibleFacts.findIndex((fact) => fact.fact_id === selectedFactId) : -1;
  const selectedIndexLabel = selectedIndex >= 0 ? `第 ${formatNumber(meta.offset + selectedIndex + 1)} 条` : '列表外事实';

  return (
    <section className="panel fact-page">
      <div className="page-section-header">
        <div>
          <h2>事实查询</h2>
          <p>用于追溯故事的原始依据：优先看 Prompt、错误、风险和待补证事实。</p>
        </div>
        <div className="page-actions">
          <TimeWindowTabs value={filters.window} onChange={(window) => updateFilters({ window })} />
          <button className="compact-button" onClick={refresh} type="button">刷新</button>
          <span className="refresh-stamp">最后刷新 {formatDateTime(lastRefresh)}</span>
        </div>
      </div>
      <div className="metric-grid fact-query-summary" aria-label="事实查询摘要">
        <MiniMetric label="事实总数" value={formatNumber(meta.total)} />
        <MiniMetric label="待补证" value={formatNumber(facts.filter((fact) => fact.quality === 'low').length)} />
        <MiniMetric label="已进入故事" value={formatNumber(facts.filter((fact) => fact.promoted_to_story).length)} />
      </div>
      <div className="fact-toolbar">
        <label className="inline-check inline-check--with-help">
          <input
            checked={filters.include_health}
            type="checkbox"
            onChange={(event) => updateFilters({ include_health: event.target.checked })}
          />
          <span>显示采集器自检与心跳</span>
          <small>默认隐藏采集器健康检查，排查采集链路时打开。</small>
        </label>
      </div>
      <div className="filter-row" aria-label="事实筛选">
        <FilterSelect label="质量" value={filters.quality} onChange={(quality) => updateFilters({ quality: quality as Filters['quality'] })}>
          <option value="all">全部</option>
          <option value="low">低</option>
          <option value="high">高</option>
          <option value="unknown">未知</option>
        </FilterSelect>
        <FilterSelect label="类型" value={filters.fact_type} onChange={(fact_type) => updateFilters({ fact_type })}>
          <option value="all">全部</option>
          <option value="content">Prompt / 消息</option>
          <option value="error">错误</option>
          <option value="tool">工具</option>
          <option value="usage">用量</option>
          <option value="risk">风险</option>
          <option value="unknown">未归类</option>
        </FilterSelect>
        <FilterSelect label="来源" value={filters.source} onChange={(source) => updateFilters({ source })}>
          <option value="all">全部</option>
          <option value="codex">Codex</option>
        </FilterSelect>
      </div>
      {state === 'loading' && <p>正在加载事实</p>}
      {state === 'error' && <p>事实查询不可用，请确认后端服务正在运行。</p>}
      {state === 'empty' && !detail && <EmptyState filters={filters} />}
      {(state === 'ready' || detail) && (
        <div className="fact-layout">
          {state === 'ready' ? (
            <FactTable
              facts={visibleFacts}
              meta={meta}
              onInspect={inspect}
              onPage={(offset) => setFilters((current) => ({ ...current, offset }))}
              selectedFactId={selectedFactId}
            />
          ) : (
            <div className="table-wrap">
              <p className="result-note">
                当前筛选没有命中列表，但已打开从故事证据链进入的事实详情；切换到“全部”可在列表中定位同一事实。
              </p>
            </div>
          )}
          {detail ? (
            <FactDetailPanel detail={detail} factIndexLabel={selectedIndexLabel} panelRef={detailRef} />
          ) : (
            <EmptyDetailPanel />
          )}
        </div>
      )}
    </section>
  );
}

const defaultFilters: Filters = {
  quality: 'all',
  fact_type: 'all',
  source: 'all',
  window: '1h',
  include_health: false,
  limit: PAGE_SIZE,
  offset: 0,
};

function EmptyState({ filters }: { filters: Filters }) {
  return (
    <p>
      当前筛选没有事实：时间窗 {filters.window}，类型 {filters.fact_type === 'all' ? '全部' : filters.fact_type}，
      采集器自检与心跳{filters.include_health ? '已显示' : '已隐藏'}。
    </p>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function FilterSelect({
  children,
  label,
  onChange,
  value
}: {
  children: ReactNode;
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
  );
}
