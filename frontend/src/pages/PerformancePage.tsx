/** 性能观测页面：汇总指标 + 任务列表 + 失败时间线（对标 McpObservationPage 结构）。 */
import { useEffect, useState } from 'react';

import type {
  PerfFailureRow,
  PerfLatencyStats,
  PerfSummary,
  PerfTaskDetail,
  PerfTasksResponse,
  PerfWindow,
} from '../api/types.performance';
import type { PerfAgentType } from '../api/performance';
import { formatNumber } from '../utils/numberFormat';
import { PerformanceFailures } from './PerformanceFailures';
import { PerformanceTaskDetail } from './PerformanceTaskDetail';
import { PerformanceTaskList } from './PerformanceTaskList';

const PERF_WINDOWS: Array<{ value: PerfWindow; label: string }> = [
  { value: '1h', label: '1小时' },
  { value: '2h', label: '2小时' },
  { value: '3h', label: '3小时' },
  { value: '6h', label: '6小时' },
  { value: '12h', label: '12小时' },
  { value: '24h', label: '24小时' },
  { value: 'today', label: '今天' },
  { value: 'week', label: '本周' },
  { value: '7d', label: '7天' },
  { value: 'all', label: '全部' },
];

const AGENT_OPTIONS: Array<{ value: PerfAgentType; label: string }> = [
  { value: '', label: '全部 Agent' },
  { value: 'workbuddy', label: 'WorkBuddy' },
  { value: 'codex', label: 'Codex' },
  { value: 'claude', label: 'Claude' },
];

interface Props {
  loadSummary: (params: { window?: PerfWindow; agent_type?: PerfAgentType }) => Promise<PerfSummary>;
  loadTasks: (params: { window?: PerfWindow; agent_type?: PerfAgentType; page?: number; page_size?: number }) => Promise<PerfTasksResponse>;
  loadFailures: (params: { window?: PerfWindow; agent_type?: PerfAgentType }) => Promise<{ failures: PerfFailureRow[] }>;
  loadTaskDetail: (traceId: string) => Promise<PerfTaskDetail>;
  /** 点击"查看会话"时跳转到会话详情并定位到具体 fact。 */
  onOpenFact?: (factId: string) => void;
}

interface SummaryState {
  data: PerfSummary | null;
  loading: boolean;
  error: boolean;
}

function metricCard(label: string, value: string, hint: string, testId: string) {
  return (
    <div className="metric" data-testid={testId}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  );
}

function latencyRow(spanType: string, stats: PerfLatencyStats) {
  const labels: Record<string, string> = { llm_call: 'LLM 调用', tool_call: '工具调用', task: '任务', mcp_call: 'MCP 调用' };
  // P1-1（审查 #2）：区分"无数据"（=0）和"样本不足"（>0 且 <20），避免误导
  const durationNoData = stats.duration_sample_count === 0;
  const durationInsufficient = !durationNoData && stats.duration_sample_count < 20;
  const ttftNoData = stats.ttft_sample_count === 0;
  const ttftInsufficient = !ttftNoData && stats.ttft_sample_count < 20;
  const isLlmCall = spanType === 'llm_call';
  const pct = (v: number) => (durationNoData || durationInsufficient ? '—' : `${formatNumber(v)}ms`);
  const ttftPct = (v: number) => (ttftNoData || ttftInsufficient || v === 0 ? '—' : `${formatNumber(v)}ms`);
  const tpsDisplay = (v: number) => (stats.tps_sample_count > 0 && v > 0 ? v.toFixed(1) : '—');
  const muted = durationNoData && (ttftNoData || !isLlmCall) && stats.tps_sample_count === 0;
  return (
    <div className={`signal-insight-card${muted ? ' muted' : ''}`} key={spanType}>
      <span>{labels[spanType] || spanType}</span>
      <strong>样本 {formatNumber(stats.sample_count)}</strong>
      <small title="百分位延迟（nearest-rank）：P50=中位数，P95=95% 请求快于此值，P99=99% 请求快于此值。单位 ms。仅统计有耗时数据的样本（duration_ms>0），样本数≥20 才计算，否则显示 —。">
        P50 {pct(stats.duration_p50_ms)} / P95 {pct(stats.duration_p95_ms)} / P99 {pct(stats.duration_p99_ms)}
      </small>
      {/* P1-5: 仅 LLM 调用显示 TTFT 行，其他类型不产出此指标 */}
      {isLlmCall && (
        <small title="TTFT（Time To First Token，首 token 延迟）：从请求发出到收到第一个 token 的耗时。单位 ms。codex 此值含 turn 内工具耗时，非纯 LLM TTFT。样本数≥20 才计算，否则显示 —。">
          TTFT P50 {ttftPct(stats.ttft_p50_ms)} / P95 {ttftPct(stats.ttft_p95_ms)}
        </small>
      )}
      <small title="TPS（Tokens Per Second，每秒 token 数）：生成速度。单位 tokens/s。当前采集器暂未采集此指标，显示 —。">
        TPS 均值 {tpsDisplay(stats.tps_avg)} / 峰值 {tpsDisplay(stats.tps_max)}
      </small>
      {durationNoData && <small className="hint">无 duration 数据，不计算百分位</small>}
      {durationInsufficient && <small className="hint">耗时样本不足 20（当前 {stats.duration_sample_count}），不计算百分位</small>}
    </div>
  );
}

export function PerformancePage({ loadSummary, loadTasks, loadFailures, loadTaskDetail, onOpenFact }: Props) {
  const [window, setWindow] = useState<PerfWindow>('24h');
  const [agentType, setAgentType] = useState<PerfAgentType>('');
  const [summary, setSummary] = useState<SummaryState>({ data: null, loading: true, error: false });
  const [tasks, setTasks] = useState<PerfTasksResponse | null>(null);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksError, setTasksError] = useState(false);
  const [taskPage, setTaskPage] = useState(1);
  const [failures, setFailures] = useState<PerfFailureRow[]>([]);
  const [failuresLoading, setFailuresLoading] = useState(true);
  const [failuresError, setFailuresError] = useState(false);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [taskDetail, setTaskDetail] = useState<PerfTaskDetail | null>(null);
  const [taskDetailLoading, setTaskDetailLoading] = useState(false);
  const [taskDetailError, setTaskDetailError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSummary((c) => ({ ...c, loading: true, error: false }));
    loadSummary({ window, agent_type: agentType })
      .then((data) => { if (!cancelled) setSummary({ data, loading: false, error: false }); })
      // R2-X35: 保留旧数据，仅设 error 标志，避免网络抖动时整页消失
      .catch(() => { if (!cancelled) setSummary((c) => ({ ...c, loading: false, error: true })); });
    return () => { cancelled = true; };
  }, [loadSummary, window, agentType]);

  useEffect(() => {
    let cancelled = false;
    setTasksLoading(true);
    setTasksError(false);
    loadTasks({ window, agent_type: agentType, page: taskPage, page_size: 20 })
      .then((data) => { if (!cancelled) { setTasks(data); setTasksLoading(false); } })
      // R2-E1: 记录错误状态，不只是静默吞掉
      .catch(() => { if (!cancelled) { setTasksLoading(false); setTasksError(true); } });
    return () => { cancelled = true; };
  }, [loadTasks, window, agentType, taskPage]);

  useEffect(() => {
    let cancelled = false;
    setFailuresLoading(true);
    setFailuresError(false);
    loadFailures({ window, agent_type: agentType })
      .then((data) => { if (!cancelled) { setFailures(data.failures); setFailuresLoading(false); } })
      // R2-E1: 记录错误状态，不只是静默吞掉
      .catch(() => { if (!cancelled) { setFailuresLoading(false); setFailuresError(true); } });
    return () => { cancelled = true; };
  }, [loadFailures, window, agentType]);

  // R2-E6: 任务详情抽屉：选中 trace_id 时加载明细
  useEffect(() => {
    if (!selectedTraceId) {
      setTaskDetail(null);
      return;
    }
    let cancelled = false;
    setTaskDetailLoading(true);
    setTaskDetailError(false);
    loadTaskDetail(selectedTraceId)
      .then((data) => { if (!cancelled) { setTaskDetail(data); setTaskDetailLoading(false); } })
      .catch(() => { if (!cancelled) { setTaskDetailLoading(false); setTaskDetailError(true); } });
    return () => { cancelled = true; };
  }, [loadTaskDetail, selectedTraceId]);

  // R2-E6: ESC 键关闭任务详情抽屉
  useEffect(() => {
    if (!selectedTraceId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedTraceId(null);
    };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, [selectedTraceId]);

  if (summary.error && !summary.data) {
    return (
      <section className="panel" data-testid="perf-page">
        <p>性能数据不可用。请确认后端服务正常。</p>
      </section>
    );
  }

  const totals = summary.data?.totals;
  const showSummaryPlaceholder = summary.loading && !summary.data;
  const latency = summary.data?.latency ?? {};

  return (
    <section className="panel" data-testid="perf-page">
      {summary.error && summary.data && (
        <div className="alert alert-warning" role="alert">数据刷新失败，显示的是上次成功获取的数据。</div>
      )}
      {summary.data?.truncated && (
        <div className="alert alert-warning" role="alert" data-testid="perf-truncated-warning">
          数据量过大，延迟统计基于最近 50,000 条信号，任务数和样本数为全量计数。
        </div>
      )}
      <section className="filter-bar" aria-label="性能筛选">
        <div className="segmented-control" aria-label="时间范围" role="group">
          {PERF_WINDOWS.map((opt) => (
            <button
              className={window === opt.value ? 'active' : ''}
              key={opt.value}
              onClick={() => { setWindow(opt.value); setTaskPage(1); }}
              type="button"
            >
              {opt.label}
            </button>
          ))}
        </div>
        <label className="compact-filter">
          Agent
          <select aria-label="Agent 类型" onChange={(e) => { setAgentType(e.target.value as PerfAgentType); setTaskPage(1); }} value={agentType}>
            {AGENT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </label>
      </section>

      <section className="metrics" aria-label="性能汇总">
        {metricCard('任务数', showSummaryPlaceholder ? '...' : formatNumber(totals?.task_count ?? 0), '窗口内任务', 'perf-summary-tasks')}
        {metricCard(
          'LLM 调用',
          showSummaryPlaceholder ? '...' : formatNumber(totals?.llm_call_count ?? 0),
          showSummaryPlaceholder
            ? '...'
            : (totals?.llm_call_count ?? 0) > 0
              ? '模型请求次数（codex 已拆分 llm_call span；claude 暂未拆分）'
              : '当前为 0：仅 codex 拆分了 llm_call span，claude 暂未拆分，筛选 claude 或全部且无 codex 数据时为 0',
          'perf-summary-llm',
        )}
        {metricCard(
          '成功率',
          showSummaryPlaceholder ? '...' : (totals?.success_rate === null || totals?.success_rate === undefined ? '—' : `${(totals.success_rate * 100).toFixed(2)}%`),
          showSummaryPlaceholder ? '...' : (totals?.llm_call_count ?? 0) === 0 ? '无 LLM 调用数据' : 'LLM 调用成功占比（不含中断）',
          'perf-summary-rate',
        )}
        {metricCard('失败数', showSummaryPlaceholder ? '...' : formatNumber(totals?.failure_count ?? 0), showSummaryPlaceholder ? '...' : `LLM 调用失败${(totals?.interrupted_count ?? 0) > 0 ? `（另 ${totals.interrupted_count} 中断）` : ''}`, 'perf-summary-failures')}
        {metricCard('工具调用', showSummaryPlaceholder ? '...' : formatNumber(totals?.tool_call_count ?? 0), '窗口内工具调用', 'perf-summary-tools')}
        {metricCard('样本数', showSummaryPlaceholder ? '...' : formatNumber(summary.data?.sample_count ?? 0), '性能信号总数', 'perf-summary-samples')}
      </section>

      {Object.keys(latency).length > 0 && (
        <section className="panel" aria-label="延迟分布" style={{ marginTop: '12px' }}>
          <div className="panel-header">
            <h2>延迟分布（按类型）</h2>
          </div>
          <div className="perf-latency-grid">
            {Object.entries(latency).map(([spanType, stats]) => latencyRow(spanType, stats))}
          </div>
        </section>
      )}

      <div style={{ marginTop: '12px' }}>
        <PerformanceTaskList data={tasks} loading={tasksLoading} error={tasksError} page={taskPage} onPageChange={setTaskPage} onTraceClick={setSelectedTraceId} onOpenFact={onOpenFact} />
      </div>

      <div style={{ marginTop: '12px' }}>
        <PerformanceFailures failures={failures} loading={failuresLoading} error={failuresError} onOpenFact={onOpenFact} />
      </div>

      {selectedTraceId && (
        <PerformanceTaskDetail
          traceId={selectedTraceId}
          detail={taskDetail}
          loading={taskDetailLoading}
          error={taskDetailError}
          onClose={() => setSelectedTraceId(null)}
          onOpenFact={onOpenFact}
        />
      )}
    </section>
  );
}