import { useEffect, useState } from 'react';

import type { CollectorsResponse, FactsResponse, RiskSummary, StoriesResponse, TimeWindow, UsageSummary } from '../api/types';
import { Metric } from '../components/Metric';
import { StoryCard } from '../components/StoryCard';
import { TimeWindowTabs } from '../components/TimeWindowTabs';
import { formatCount, formatNumber } from '../utils/numberFormat';
import { DashboardInvestigationSummary, type FactJumpFilters } from './DashboardInvestigationSummary';
import {
  factTypeLabel,
  formatDateTime,
  qualityLabel,
  reasonCodeLabel,
  sourceStatusLabel,
} from './dashboardLabels';
import { UsageGovernanceSummary } from './UsageGovernanceSummary';

interface Props {
  loadCollectors: () => Promise<CollectorsResponse>;
  loadFacts: (filters: { window: TimeWindow; include_health: boolean }) => Promise<FactsResponse>;
  loadStories: (options: { window: TimeWindow; queue: 'actionable' | 'all' }) => Promise<StoriesResponse>;
  loadUsageSummary: (window: TimeWindow) => Promise<UsageSummary>;
  loadRiskSummary: (window: TimeWindow) => Promise<RiskSummary>;
  onOpenStory: (storyId: string) => void;
  onOpenFacts?: (filters: FactJumpFilters) => void;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | {
      status: 'ready';
      collectors: CollectorsResponse;
      facts: FactsResponse;
      stories: StoriesResponse;
      usage: UsageSummary;
      risks: RiskSummary;
    };

export function DashboardPage({
  loadCollectors,
  loadFacts,
  loadRiskSummary,
  loadStories,
  loadUsageSummary,
  onOpenFacts,
  onOpenStory
}: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [window, setWindow] = useState<TimeWindow>('1h');
  const [refreshToken, setRefreshToken] = useState(0);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    Promise.all([
      loadCollectors(),
      loadFacts({ window, include_health: false }),
      loadStories({ window, queue: 'actionable' }),
      loadUsageSummary(window),
      loadRiskSummary(window)
    ])
      .then(([collectors, facts, stories, usage, risks]) => {
        if (!cancelled) {
          setState({ status: 'ready', collectors, facts, stories, usage, risks });
          setLastRefresh(new Date().toISOString());
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [loadCollectors, loadFacts, loadRiskSummary, loadStories, loadUsageSummary, refreshToken, window]);

  if (state.status === 'loading') {
    return (
      <section className="panel">
        <h2>正在加载观测数据</h2>
        <p>读取采集器、事实、故事队列和治理指标。</p>
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
  const activeStories = state.stories.stories.filter((story) => story.attention_state !== 'handled_hidden');
  const highRiskCount = state.risks.signals.reduce((total, item) => total + item.count, 0);

  return (
    <div className="dashboard workbench" aria-label="观察故事运营台">
      <section className="context-bar">
        <div>
          <strong>观察故事运营台</strong>
          <span>默认只看最近 1 小时；故事队列只放需要人工处理的错误、风险和补证事项。</span>
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
          <Mini label="最近事实" value={latestFactTitle(latestFact)} />
          <Mini label="最近心跳" value={formatDateTime(latestCollector?.last_heartbeat_at)} />
        </div>
      </section>

      <section className="metrics" aria-label="核心指标">
        <Metric
          label="采集器"
          value={`${formatNumber(onlineCollectors.length)} / ${formatNumber(state.collectors.collectors.length)}`}
          note="在线 / 总数"
        />
        <Metric label="事实" value={formatNumber(state.facts.facts.length)} note="已接收结构化事实" />
        <Metric label="待处理故事" value={formatNumber(activeStories.length)} note="active / needs_review" />
        <Metric label="风险信号" value={formatNumber(highRiskCount)} note="高风险与敏感触达" />
      </section>

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
              <Mini label="事实质量" value={qualitySummary(state.facts)} />
              <Mini label="待传 outbox" value={formatNumber(sumBacklog(state.collectors))} />
              <Mini label="重点队列" value={queueSummary(activeStories.length)} />
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
                      {sourceStatusLabel(collector.source_status)} / {reasonCodeLabel(collector.reason_code)}
                    </span>
                    <span className="badge teal">backlog {formatNumber(collector.outbox_backlog)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        <section className="panel flush story-workbench" aria-label="观察故事">
          <div className="panel-header">
            <h2>观察故事队列</h2>
            <span className="badge violet">{formatNumber(activeStories.length)} 条待看</span>
          </div>
          <p className="panel-intro">每条故事都应该能回答：发生了什么、影响谁、为什么值得处理、下一步怎么做。</p>
          <div className="panel-body">
            {activeStories.length === 0 ? (
              <p>当前没有需要人工处理的故事；请确认 collector 已运行并有 Codex 会话事实入库。</p>
            ) : (
              <div className="story-list">
                {activeStories.map((story) => (
                  <StoryCard key={story.story_id} story={story} onOpen={onOpenStory} />
                ))}
              </div>
            )}
          </div>
        </section>

        <aside className="side-stack" aria-label="证据、用量和风险">
        <DashboardInvestigationSummary
          facts={state.facts}
          onOpenFacts={onOpenFacts}
          risks={state.risks}
          usage={state.usage}
          window={window}
        />
        <UsageGovernanceSummary usage={state.usage} risks={state.risks} />
        </aside>
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function sumBacklog(data: CollectorsResponse): number {
  return data.collectors.reduce((total, collector) => total + collector.outbox_backlog, 0);
}

function qualitySummary(data: FactsResponse): string {
  const high = data.facts.filter((fact) => fact.quality === 'high').length;
  const low = data.facts.filter((fact) => fact.quality === 'low').length;
  return `高置信 ${formatNumber(high)} / 待补证 ${formatNumber(low)}`;
}

function latestFactTitle(fact: FactsResponse['facts'][number] | undefined): string {
  if (!fact) return '暂无事实';
  const raw = fact.raw_available ? '已上传原文' : '未上传原文';
  return `最近上报：${factTypeLabel(fact.category || fact.fact_type)}，${qualityLabel(fact.quality)}可信，${raw}`;
}

function queueSummary(activeCount: number): string {
  return activeCount > 0 ? `${formatCount(activeCount, '个故事待处理')}` : '暂无待处理故事';
}
