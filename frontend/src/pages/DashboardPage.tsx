import { useEffect, useState } from 'react';

import type { CollectorsResponse, DashboardSummary, FactsResponse, RiskSummary, SignalsResponse, TimeWindow, UsageSummary } from '../api/types';
import { Metric } from '../components/Metric';
import { SignalCard } from '../components/SignalCard';
import { TimeWindowTabs } from '../components/TimeWindowTabs';
import { formatNumber } from '../utils/numberFormat';
import {
  collectorRuntimeLabel,
  emptyUsage,
  formatDateTime,
  latestFactTitle,
  qualitySummary,
  queueSummary,
  reasonCodeLabel,
  sumBacklog,
} from './dashboardLabels';
import { UsageGovernanceSummary } from './UsageGovernanceSummary';
import { UsageTrendChart } from './UsageTrendChart';

interface Props {
  loadDashboardSummary: (window: TimeWindow) => Promise<DashboardSummary>;
  loadSignals: (options: { window: TimeWindow; page?: number; page_size?: number }) => Promise<SignalsResponse>;
  loadUsageSummary: (window: TimeWindow) => Promise<UsageSummary>;
  loadRiskSummary: (window: TimeWindow) => Promise<RiskSummary>;
  onOpenSignal: (signalId: string) => void;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | {
      status: 'ready';
      collectors: CollectorsResponse;
      collectorCounts: DashboardSummary['collectors'];
      facts: FactsResponse;
      signals: SignalsResponse;
      usage: UsageSummary;
      risks: RiskSummary;
    };

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function DashboardPage({
  loadDashboardSummary,
  loadRiskSummary,
  loadSignals,
  loadUsageSummary,
  onOpenSignal
}: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [window, setWindow] = useState<TimeWindow>('1h');
  const [refreshToken, setRefreshToken] = useState(0);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    loadDashboardSummary(window)
      .then((summary) => {
        if (!cancelled) {
          setState({
            status: 'ready',
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
            usage: emptyUsage(window),
            risks: { mode: 'summary', window, signals: summary.risks.top }
          });
          setLastRefresh(new Date().toISOString());
        }
        return Promise.allSettled([
          loadSignals({ window, page: 1, page_size: 20 }),
          loadUsageSummary(window),
          loadRiskSummary(window)
        ]);
      })
      .then((results) => {
        if (cancelled) return;
        setState((current) => {
          if (current.status !== 'ready') return current;
          const [signals, usage, risks] = results;
          return {
            ...current,
            signals: signals.status === 'fulfilled' ? signals.value : current.signals,
            usage: usage.status === 'fulfilled' ? usage.value : current.usage,
            risks: risks.status === 'fulfilled' ? risks.value : current.risks
          };
        });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [loadDashboardSummary, loadRiskSummary, loadSignals, loadUsageSummary, refreshToken, window]);

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
  const latestFact = state.facts.facts[0];
  const latestCollector = state.collectors.collectors[0];
  const activeSignals = state.signals.signals.filter((signal) => signal.decision_state !== 'handled');
  const highRiskCount = state.risks.signals.reduce((total, item) => total + item.count, 0);

  return (
    <div className="dashboard workbench" aria-label="行为风险信号台" data-testid="dashboard-page">
      <section className="context-bar">
        <div>
          <strong>行为风险信号台</strong>
          <span>默认只看最近 1 小时；信号队列只放可以判断和下钻的行为风险模式。</span>
        </div>
        <div className="context-actions">
          <TimeWindowTabs value={window} onChange={setWindow} />
          <button className="compact-button" onClick={() => setRefreshToken((value) => value + 1)} type="button">
            刷新
          </button>
          <span className="refresh-stamp">最后刷新 {formatDateTime(lastRefresh)}</span>
        </div>
        <div className="mini-grid">
          <Mini label="当前采集器" value={latestCollector?.display_name ?? '未注册'} />
          <Mini label="最近命中" value={latestFactTitle(latestFact)} />
          <Mini label="最近心跳" value={formatDateTime(latestCollector?.last_heartbeat_at)} />
        </div>
      </section>

      <section className="metrics" aria-label="核心指标">
        <Metric
          label="采集器"
          value={`${formatNumber(state.collectorCounts.online)} / ${formatNumber(state.collectorCounts.total)}`}
          note="在线 / 总数"
        />
        <Metric label="会话内容" value={formatNumber(state.facts.total ?? state.facts.facts.length)} note="当前窗口可追溯内容" />
        <Metric label="待判断信号" value={formatNumber(state.signals.total ?? activeSignals.length)} note="unread / needs_review" />
        <Metric label="风险信号" value={formatNumber(highRiskCount)} note="高风险与敏感触达" />
      </section>

      <UsageTrendChart usage={state.usage} />

      <div className="workbench-grid">
        <aside className="panel flush workbench-side" aria-label="观测上下文">
          <div className="panel-header">
            <h2>接入与筛选</h2>
            <span className={onlineCollectors.length ? 'badge green' : 'badge amber'}>
              {onlineCollectors.length ? '已收到心跳' : '等待采集器'}
            </span>
          </div>
          <div className="panel-body">
            <div className="context-stack">
              <Mini label="命中质量" value={qualitySummary(state.facts)} />
              <Mini label="待传 outbox" value={formatNumber(sumBacklog(state.collectors))} />
              <Mini label="重点队列" value={queueSummary(activeSignals.length)} />
            </div>
            {state.collectors.collectors.length === 0 ? (
              <p>还没有采集器注册。请下载 Windows 包并运行 start。</p>
            ) : (
              <div className="row-list">
                {state.collectors.collectors.slice(0, 4).map((collector) => (
                  <div className="collector-row" key={collector.collector_id}>
                    <div className="collector-row__identity">
                      <strong>{collector.display_name}</strong>
                      <small>{collector.collector_id}</small>
                    </div>
                    <span className="collector-row__status">
                      {collectorRuntimeLabel(collector.source_status, collector.runtime_phase)} / {reasonCodeLabel(collector.reason_code)}
                    </span>
                    <span className="badge teal">backlog {formatNumber(collector.outbox_backlog)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        <section className="panel flush signal-workbench" aria-label="行为风险信号" data-testid="signal-queue">
          <div className="panel-header">
            <h2>行为风险信号</h2>
            <span className="badge violet">{formatNumber(state.signals.total ?? activeSignals.length)} 条待看</span>
          </div>
          <p className="panel-intro">每条信号都对应一个可判断的风险模式，并按会话、对象或失败类型组织证据。</p>
          <div className="panel-body">
            {activeSignals.length === 0 ? (
              <p>当前没有需要人工处理的信号；请确认 collector 已运行并有 Codex 会话内容入库。</p>
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

        <aside className="side-stack" aria-label="用量和风险">
          <UsageGovernanceSummary usage={state.usage} risks={state.risks} />
        </aside>
      </div>
    </div>
  );
}
