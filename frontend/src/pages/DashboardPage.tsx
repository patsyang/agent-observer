import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { RefreshCw } from 'lucide-react';

import type { CollectorsResponse, DashboardSummary, FactsResponse, ProcessingStatus, RiskSummary, SignalSummary, SignalsResponse, TimeWindowParam, UsageSummary } from '../api/types';
import { Metric } from '../components/Metric';
import { RiskHeadlineMetric } from '../components/RiskHeadlineMetric';
import { SignalCard } from '../components/SignalCard';
import { riskFamilyLabel } from '../components/signalLabels';
import { quickTimeOptions } from '../components/timeRangeOptions';
import { formatNumber } from '../utils/numberFormat';
import { emptyUsage, formatDateTime } from './dashboardLabels';
import { DashboardAccessPanel } from './DashboardAccessPanel';
import { TimeRangePicker } from './TimeRangePicker';
import { UsageTrendChart } from './UsageTrendChart';
import { ProcessingStatusBanner } from './ProcessingStatusBanner';
import { useProcessingStatusPolling } from './useProcessingStatusPolling';
interface Props {
  loadDashboardSummary: (window: TimeWindowParam, agentType?: AgentType, startAt?: string, endAt?: string) => Promise<DashboardSummary>;
  loadSignals: (options: { window: TimeWindowParam; start_at?: string; end_at?: string; workspace_query?: string; agent_type?: AgentType; family?: string; page?: number; page_size?: number }) => Promise<SignalsResponse>;
  loadSignalSummary: (window: TimeWindowParam, agentType?: AgentType, startAt?: string, endAt?: string) => Promise<SignalSummary>;
  loadUsageSummary: (window: TimeWindowParam, agentType?: AgentType, startAt?: string, endAt?: string) => Promise<UsageSummary>;
  loadRiskSummary: (window: TimeWindowParam, agentType?: AgentType, startAt?: string, endAt?: string) => Promise<RiskSummary>;
  loadProcessingStatus: () => Promise<ProcessingStatus>;
  onOpenSignal: (signalId: string) => void;
}
type AgentType = '' | 'codex' | 'workbuddy' | 'claude';
type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | {
      status: 'ready';
      detailsLoading: boolean;
      collectors: CollectorsResponse;
      collectorCounts: DashboardSummary['collectors'];
      facts: FactsResponse;
      signals: SignalsResponse;
      signalSummary: SignalSummary | null;
      usage: UsageSummary;
      risks: RiskSummary;
      processing: ProcessingStatus;
      highPriorityCount: number;
      activeConversations: number;
    };
function formatPercent(value?: number): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}

function agentLabel(agentType: AgentType): string {
  if (agentType === 'claude') return 'Claude Code';
  if (agentType === 'codex') return 'Codex';
  if (agentType === 'workbuddy') return 'WorkBuddy';
  return 'Agent';
}

export function DashboardPage({
  loadDashboardSummary,
  loadProcessingStatus,
  loadRiskSummary,
  loadSignalSummary,
  loadSignals,
  loadUsageSummary,
  onOpenSignal
}: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [familyFilter, setFamilyFilter] = useState<string | null>(null);
  const skipFamilyEffect = useRef(true);
  const [submittedFilters, setSubmittedFilters] = useState({
    window: '1h' as TimeWindowParam | '',
    start_at: '',
    end_at: '',
    agentType: '' as AgentType,
    workspaceQuery: '',
  });
  const [draftFilters, setDraftFilters] = useState(submittedFilters);
  const [refreshToken, setRefreshToken] = useState(0);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [sidebarSlot, setSidebarSlot] = useState<HTMLElement | null>(null);
  const [topbarStatusSlot, setTopbarStatusSlot] = useState<HTMLElement | null>(null);
  const updateProcessingStatus = useCallback((processing: ProcessingStatus) => {
    setState((current) => (current.status === 'ready' ? { ...current, processing } : current));
  }, []);
  useProcessingStatusPolling(state.status === 'ready' ? state.processing.state : 'idle', loadProcessingStatus, updateProcessingStatus);
  useEffect(() => {
    setSidebarSlot(document.getElementById('dashboard-sidebar-slot'));
    setTopbarStatusSlot(document.getElementById('dashboard-topbar-status-slot'));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const { agentType, end_at, start_at, window, workspaceQuery } = submittedFilters;
    const requestWindow: TimeWindowParam = window || 'custom';
    setState({ status: 'loading' });
    loadDashboardSummary(requestWindow, agentType, start_at, end_at)
      .then((summary) => {
        if (!cancelled) {
          setState({
            status: 'ready',
            detailsLoading: true,
            collectors: { collectors: summary.collectors.items },
            collectorCounts: summary.collectors,
            facts: { facts: summary.facts.items, total: summary.facts.total, page: 1, page_size: 5, has_more: summary.facts.total > summary.facts.items.length },
            signals: {
              signals: summary.signals.items,
              total: summary.signals.total,
              page: 1,
              page_size: 20,
              has_more: summary.signals.total > summary.signals.items.length
            },
            usage: emptyUsage(requestWindow),
            signalSummary: null,
            risks: { mode: 'summary', window: requestWindow, signals: summary.risks.top },
            processing: { state: 'idle', counts: { pending: 0, running: 0, succeeded: 0, failed: 0 }, latest_failed: null },
            highPriorityCount: summary.signals.high_priority_count ?? 0,
            activeConversations: summary.active_conversations ?? 0,
          });
          setLastRefresh(new Date().toISOString());
        }
        return Promise.allSettled([
          loadSignals({ window: requestWindow, start_at, end_at, workspace_query: workspaceQuery.trim(), agent_type: agentType, family: familyFilter ?? undefined, page: 1, page_size: 20 }),
          loadSignalSummary(requestWindow, agentType, start_at, end_at),
          loadUsageSummary(requestWindow, agentType, start_at, end_at),
          loadRiskSummary(requestWindow, agentType, start_at, end_at),
          loadProcessingStatus()
        ]);
      })
      .then((results) => {
        if (cancelled) return;
        setState((current) => {
          if (current.status !== 'ready') return current;
          const [signals, signalSummaryResult, usage, risks, processing] = results;
          const emptySignals: SignalsResponse = { signals: [], total: 0, page: 1, page_size: 20, has_more: false };
          const emptyRisks: RiskSummary = { mode: 'summary', window: requestWindow, signals: [] };
          return {
            ...current,
            detailsLoading: false,
            signals: signals.status === 'fulfilled' ? signals.value : emptySignals,
            signalSummary: signalSummaryResult.status === 'fulfilled' ? signalSummaryResult.value : current.signalSummary,
            usage: usage.status === 'fulfilled' ? usage.value : emptyUsage(requestWindow),
            risks: risks.status === 'fulfilled' ? risks.value : emptyRisks,
            processing: processing.status === 'fulfilled' ? processing.value : current.processing
          };
        });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
    // familyFilter is intentionally excluded — family-only changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadDashboardSummary, loadProcessingStatus, loadRiskSummary, loadSignalSummary, loadSignals, loadUsageSummary, refreshToken, submittedFilters]);

  // Family-only filter: re-fetch just the signal list without disturbing metrics/summary.
  useEffect(() => {
    if (skipFamilyEffect.current) {
      skipFamilyEffect.current = false;
      return;
    }
    if (state.status !== 'ready') return;
    let cancelled = false;
    const { agentType, end_at, start_at, window, workspaceQuery } = submittedFilters;
    const requestWindow: TimeWindowParam = window || 'custom';
    loadSignals({ window: requestWindow, start_at, end_at, workspace_query: workspaceQuery.trim(), agent_type: agentType, family: familyFilter ?? undefined, page: 1, page_size: 20 })
      .then((signals) => {
        if (!cancelled) {
          setState((current) => (current.status === 'ready' ? { ...current, signals } : current));
        }
      })
      .catch(() => {
        if (!cancelled) {
          const emptySignals: SignalsResponse = { signals: [], total: 0, page: 1, page_size: 20, has_more: false };
          setState((current) => (current.status === 'ready' ? { ...current, signals: emptySignals } : current));
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [familyFilter]);
  if (state.status === 'loading') {
    return (
      <section className="panel">
        <h2>正在加载观测数据</h2>
        <p>读取采集器、会话信号和用量趋势。</p>
      </section>
    );
  }

  if (state.status === 'error') {
    return (
      <section className="panel">
        <h2>观测数据不可用</h2>
        <p>请确认后端服务在 127.0.0.1:8765 运行。</p>
        <button onClick={() => setRefreshToken((value) => value + 1)}>重试</button>
      </section>
    );
  }

  const onlineCollectors = state.collectors.collectors.filter((collector) => collector.source_status === 'online');
  const activeSignals = state.signals.signals.filter((signal) => signal.decision_state !== 'handled');
  const isLoading = state.detailsLoading;
  const submitFilters = () => {
    setSubmittedFilters({ ...draftFilters, workspaceQuery: draftFilters.workspaceQuery.trim() });
    setRefreshToken((value) => value + 1);
  };

  return (
    <div className="dashboard workbench" aria-label="行为风险信号台" data-testid="dashboard-page">
      {sidebarSlot && createPortal(
        <DashboardAccessPanel
          activeSignalCount={activeSignals.length}
          collectors={state.collectors}
          facts={state.facts}
          onlineCount={onlineCollectors.length}
        />,
        sidebarSlot
      )}
      {topbarStatusSlot && createPortal(<ProcessingStatusBanner status={state.processing} />, topbarStatusSlot)}
      <section className="context-bar">
        <div className="context-actions">
          <div className="compact-filter dashboard-time-filter">
            <span>时间</span>
            <TimeRangePicker
              end={draftFilters.end_at}
              onApply={(value) => setDraftFilters((current) => ({ ...current, ...value }))}
              options={quickTimeOptions}
              start={draftFilters.start_at}
              window={draftFilters.window}
            />
          </div>
          <label className="compact-filter">
            Agent类型
            <select
              aria-label="筛选Agent类型"
              onChange={(event) => setDraftFilters((current) => ({ ...current, agentType: event.target.value as AgentType }))}
              value={draftFilters.agentType}
            >
              <option value="">全部</option>
              <option value="codex">Codex</option>
              <option value="claude">Claude Code</option>
              <option value="workbuddy">WorkBuddy</option>
            </select>
          </label>
          <label className="compact-filter">
            工作区
            <input
              aria-label="筛选工作区"
              onChange={(event) => setDraftFilters((current) => ({ ...current, workspaceQuery: event.target.value }))}
              placeholder="别名/路径"
              value={draftFilters.workspaceQuery}
            />
          </label>
          <button
            aria-label="刷新"
            className="icon-button dashboard-refresh-button"
            disabled={isLoading}
            onClick={submitFilters}
            title="刷新"
            type="button"
          >
            <RefreshCw aria-hidden="true" size={16} />
          </button>
          <span className="refresh-stamp">最后刷新 {formatDateTime(lastRefresh)}</span>
        </div>
      </section>

      <section className="metrics" aria-label="核心指标">
        <Metric
          label="采集器"
          value={`${formatNumber(state.collectorCounts.online)} / ${formatNumber(state.collectorCounts.total)}`}
          note="在线 / 总数"
        />
        <Metric label="活跃对话" value={formatNumber(state.activeConversations)} note="窗口内有活动的对话" />
        <Metric label="实际计算Token" value={formatNumber(state.usage.totals.effective_units)} note="非缓存输入 + 输出" />
        <Metric label={`缓存命中 (${formatPercent(state.usage.totals.cache_hit_rate)})`} value={formatNumber(state.usage.totals.cached_input_units)} note="可复用输入" />
        <RiskHeadlineMetric
          summary={state.signalSummary}
          loading={isLoading}
          activeFamily={familyFilter}
          onSelectFamily={setFamilyFilter}
        />
      </section>

      <div className="usage-row" data-testid="usage-row">
        <UsageTrendChart loading={isLoading} usage={state.usage} />
      </div>

      <div className="workbench-grid">
        <section className="panel flush signal-workbench" aria-label="行为风险信号" data-testid="signal-queue">
          <div className="panel-header">
            <h2>行为风险信号</h2>
            <span className="badge violet">
              {familyFilter ? `${riskFamilyLabel(familyFilter)} · ` : ''}{formatNumber(state.signals.total ?? activeSignals.length)} 条待看
            </span>
          </div>
          <p className="panel-intro">每条信号都对应一个可判断的风险模式，并按会话、对象或失败类型组织证据。</p>
          <div className="panel-body">
            {isLoading ? (
              <p>正在加载信号...</p>
            ) : activeSignals.length === 0 ? (
              <p>当前没有需要人工处理的信号；请确认 collector 已运行并有 {agentLabel(submittedFilters.agentType)} 会话内容入库。</p>
            ) : (
              <div className="signal-list">
                {activeSignals.map((signal) => (
                  <SignalCard key={signal.signal_id} signal={signal} onOpen={onOpenSignal} />
                ))}
                {state.signals.has_more && <div className="list-footer">更多信号请进入分页列表继续查看。</div>}
              </div>
            )}
          </div>
        </section>

      </div>
    </div>
  );
}
