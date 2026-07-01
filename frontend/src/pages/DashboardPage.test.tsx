import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DashboardSummary, RiskSummary, SignalsResponse, UsageSummary } from '../api/types';
import { DashboardPage } from './DashboardPage';

const usage: UsageSummary = {
  window: 'today',
  bucket_size_minutes: 60,
  totals: {
    effective_units: 3175,
    unknown_units: 1015,
    cached_input_units: 900,
    input_token_units: 3000,
    output_token_units: 1075,
    total_token_units: 4075,
    cache_write_input_units: 0,
    reasoning_output_units: 0,
    credit_total: 0,
    cache_observed_input_units: 3000,
    cache_hit_rate: 0.3
  },
  trend: [
    { bucket: '2026-06-21T01:00:00+00:00', effective_units: 100, unknown_units: 0, cached_input_units: 20, input_token_units: 100, output_token_units: 20, total_token_units: 120, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 100, cache_hit_rate: 0.2 },
    { bucket: '2026-06-21T01:05:00+00:00', effective_units: 3075, unknown_units: 1015, cached_input_units: 880, input_token_units: 2900, output_token_units: 1055, total_token_units: 3955, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 2900, cache_hit_rate: 0.3034 }
  ],
  rollups: [
    {
      rollup_id: 'today:session:session-001:implementation',
      window: 'today',
      scope: 'session',
      scope_value: 'session-001',
      units: 1120,
      activity_tag: 'implementation',
      evidence_refs: ['proj-usage-effective-001']
    },
    {
      rollup_id: 'today:conversation:conversation-001:bug_fix',
      window: 'today',
      scope: 'conversation',
      scope_value: 'conversation-001',
      units: 2040,
      activity_tag: 'bug_fix',
      evidence_refs: ['proj-usage-fix-001']
    },
    {
      rollup_id: 'today:activity_tag:unknown:unknown',
      window: 'today',
      scope: 'activity_tag',
      scope_value: 'unknown',
      units: 1015,
      activity_tag: 'unknown',
      evidence_refs: ['proj-usage-unknown-001']
    }
  ]
};

function usageWithTotal(total: number): UsageSummary {
  return {
    window: '1h',
    bucket_size_minutes: 1,
    totals: {
      effective_units: total,
      unknown_units: 0,
      cached_input_units: 0,
      input_token_units: total,
      output_token_units: 0,
      total_token_units: total,
      cache_write_input_units: 0,
      reasoning_output_units: 0,
      credit_total: 0,
      cache_observed_input_units: total,
      cache_hit_rate: 0
    },
    trend: [
      { bucket: '2026-06-21T01:00:00+00:00', effective_units: total, unknown_units: 0, cached_input_units: 0, input_token_units: total, output_token_units: 0, total_token_units: total, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: total, cache_hit_rate: 0 }
    ],
    rollups: [
      {
        rollup_id: `1h:total:all:${total}`,
        window: '1h',
        scope: 'total',
        scope_value: 'all',
        units: total,
        activity_tag: 'all',
        evidence_refs: []
      }
    ]
  };
}

const risks: RiskSummary = {
  signals: [
    {
      risk_type: 'sensitive_content_exposure',
      object_type: 'configuration',
      count: 1001,
      highest_severity: 'high',
      top_examples: ['E2E sensitive configuration touched']
    }
  ]
};

const summary: DashboardSummary = {
  window: '1h',
  collectors: {
    total: 6,
    online: 1,
    degraded: 0,
    offline: 0,
    items: [
    {
      collector_id: 'windows-collector',
      display_name: 'windows-collector',
      hostname_hash: 'host-hash',
      windows_username_hash: 'user-hash',
      protocol_version: 'agent-observer-telemetry/v3',
      agent_version: '0.3.0',
      source_status: 'online',
      reason_code: 'run_once',
      policy_version: 1,
      last_heartbeat_at: '2026-06-19T11:30:03+08:00',
      outbox_backlog: 0,
      runtime_phase: 'uploading',
      last_seen_at: '2026-06-19T11:30:03+08:00',
      last_cycle_duration_ms: 3100,
      last_error: null,
      sources: [{
        source_id: 'codex-local',
        collector_id: 'windows-collector',
        agent_type: 'codex',
        source_kind: 'codex_local',
        display_name: 'Codex Local',
        capabilities: { raw_upload_default: true },
        source_status: 'online',
        reason_code: 'run_once',
        last_seen_at: '2026-06-19T11:30:03+08:00'
      }]
    }
    ]
  },
  facts: {
    total: 1,
    items: [
    {
      fact_id: 'windows-collector-health-1',
      fact_type: 'collector_health',
      category: 'collector_health',
      quality: 'high',
      severity: 'low',
      summary: '采集器完成一次安全自检，状态、游标和 outbox 已结构化上报。',
      occurred_at: '2026-06-19T11:30:03+08:00',
      source: 'codex',
      promoted_to_signal: false
    }
    ]
  },
  signals: { total: 0, items: [] },
  risks: { total: 1, top: risks.signals }
};

const signalPage: SignalsResponse = { signals: [], total: 0, page: 1, page_size: 20, has_more: false };
const processingStatus = {
  state: 'pending' as const,
  counts: { pending: 2, running: 0, succeeded: 1, failed: 0 },
  latest_failed: null
};

describe('DashboardPage', () => {
  afterEach(() => {
    vi.useRealTimers();
    document.getElementById('dashboard-sidebar-slot')?.remove();
    document.getElementById('dashboard-topbar-status-slot')?.remove();
  });

  it('renders signals and usage trend instead of usage anomaly investigation', async () => {
    appendDashboardSlots();
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadSignals = vi.fn(async () => signalPage);
    const loadUsageSummary = vi.fn(async () => usage);
    const loadRiskSummary = vi.fn(async () => risks);
    const loadProcessingStatus = vi.fn(async () => processingStatus);
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadSignals={loadSignals}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        loadProcessingStatus={loadProcessingStatus}
        onOpenSignal={() => {}}
      />
    );

    const coreMetrics = await screen.findByLabelText('核心指标');
    expect(screen.getByLabelText('用量趋势')).toBeInTheDocument();
    expect(screen.getByTestId('usage-row')).toContainElement(screen.getByLabelText('用量趋势'));
    expect(screen.queryByLabelText('使用与风险治理')).not.toBeInTheDocument();
    expect(await screen.findByTestId('dashboard-sidebar-context')).toHaveTextContent('接入与筛选');
    expect(screen.getByLabelText('选择时间范围内实际计算 token 与缓存命中 token 柱状图')).toBeInTheDocument();
    expect(screen.getAllByText('windows-collector').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('行为风险信号')).toBeInTheDocument();
    expect(screen.getByLabelText('派生计算状态')).toHaveTextContent('派生计算：待处理');
    expect(screen.getByLabelText('派生计算状态')).toHaveTextContent('信号更新中');
    expect(screen.queryByText('原始会话和用量已入库，信号正在更新')).not.toBeInTheDocument();
    expect(screen.queryByText('行为风险信号台')).not.toBeInTheDocument();
    expect(screen.queryByText(/默认只看最近 1 小时/)).not.toBeInTheDocument();
    expect(screen.getByText('会话内容')).toBeInTheDocument();
    expect(screen.queryByText(/最近命中：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/未上传原文/)).not.toBeInTheDocument();
    expect(screen.getByText('1 / 6')).toBeInTheDocument();
    expect(screen.getByText(/当前没有需要人工处理的信号/)).toBeInTheDocument();
    expect(within(coreMetrics).getByText('实际计算Token')).toBeInTheDocument();
    expect(within(coreMetrics).getByText('缓存命中 (30.0%)')).toBeInTheDocument();
    expect(within(coreMetrics).getByText('待处理信号')).toBeInTheDocument();
    expect(within(coreMetrics).getByText('3,175')).toBeInTheDocument();
    expect(within(coreMetrics).getByText('900')).toBeInTheDocument();
    expect(within(coreMetrics).getByText('0')).toBeInTheDocument();
    expect(screen.getByText(/实际计算Token 3,175/)).toBeInTheDocument();
    expect(screen.queryByText('未知活动')).not.toBeInTheDocument();
    expect(screen.queryByText('模型调用实际计算 token')).not.toBeInTheDocument();
    expect(screen.queryByText('当前队列待看')).not.toBeInTheDocument();
    expect(screen.queryByText(/活动：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/风险：/)).not.toBeInTheDocument();
    expect(screen.queryByText('当前采集器')).not.toBeInTheDocument();
    expect(screen.queryByText('最近命中')).not.toBeInTheDocument();
    expect(screen.getByLabelText('筛选工作区')).toBeInTheDocument();
    expect(screen.getByLabelText('筛选Agent类型')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Claude Code' })).toHaveAttribute('value', 'claude');
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('时间范围：1小时'));
    expect(screen.getByRole('button', { name: '今天' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '本周' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '3小时' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '6小时' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '12小时' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '24小时' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '7天' })).not.toBeInTheDocument();
    expect(loadSignals).toHaveBeenCalledWith({ window: '1h', start_at: '', end_at: '', workspace_query: '', agent_type: '', page: 1, page_size: 20 });
    expect(loadUsageSummary).toHaveBeenCalledWith('1h', '', '', '');
    expect(loadRiskSummary).toHaveBeenCalledWith('1h', '', '', '');
    expect(loadDashboardSummary).toHaveBeenCalledWith('1h', '', '', '');
    expect(loadProcessingStatus).toHaveBeenCalled();
  });

  it('refreshes dashboard data without changing the selected time window', async () => {
    appendDashboardSlots();
    const user = userEvent.setup();
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadSignals = vi.fn(async () => signalPage);
    const loadUsageSummary = vi.fn(async (_window, agentType) => (
      agentType === 'workbuddy' ? usageWithTotal(222) : usageWithTotal(111)
    ));
    const loadRiskSummary = vi.fn(async () => risks);
    const loadProcessingStatus = vi.fn(async () => processingStatus);
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadSignals={loadSignals}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        loadProcessingStatus={loadProcessingStatus}
        onOpenSignal={() => {}}
      />
    );

    await screen.findByText('行为风险信号');
    await user.click(screen.getByLabelText('时间范围：1小时'));
    await user.click(screen.getByRole('button', { name: '今天' }));
    await user.selectOptions(screen.getByLabelText('筛选Agent类型'), 'workbuddy');
    expect(loadDashboardSummary).toHaveBeenCalledTimes(1);
    expect(loadRiskSummary).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(loadDashboardSummary).toHaveBeenLastCalledWith('today', 'workbuddy', '', ''));
    await waitFor(() => expect(within(screen.getByLabelText('核心指标')).getByText('222')).toBeInTheDocument());
    expect(screen.getAllByText(/实际计算Token 222/).length).toBeGreaterThanOrEqual(1);
    expect(loadRiskSummary).toHaveBeenLastCalledWith('today', 'workbuddy', '', '');
    expect(loadDashboardSummary).toHaveBeenCalledTimes(2);
    expect(loadRiskSummary).toHaveBeenCalledTimes(2);
    expect(screen.getByText(/最后刷新/)).toBeInTheDocument();
  });

  it('submits custom time range only after refresh', async () => {
    appendDashboardSlots();
    const user = userEvent.setup();
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadSignals = vi.fn(async () => signalPage);
    const loadUsageSummary = vi.fn(async () => usage);
    const loadRiskSummary = vi.fn(async () => risks);
    const loadProcessingStatus = vi.fn(async () => processingStatus);
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadSignals={loadSignals}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        loadProcessingStatus={loadProcessingStatus}
        onOpenSignal={() => {}}
      />
    );

    await screen.findByText('行为风险信号');
    await user.click(screen.getByLabelText('时间范围：1小时'));
    fireEvent.change(screen.getByLabelText('开始'), { target: { value: '2026-06-21T01:00:00' } });
    fireEvent.change(screen.getByLabelText('结束'), { target: { value: '2026-06-21T03:00:00' } });
    await user.click(screen.getByRole('button', { name: '确认' }));
    expect(loadDashboardSummary).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(loadDashboardSummary).toHaveBeenCalledTimes(2));
    const expectedStart = new Date('2026-06-21T01:00:00').toISOString();
    const expectedEnd = new Date('2026-06-21T03:00:00').toISOString();
    expect(loadDashboardSummary).toHaveBeenLastCalledWith('custom', '', expectedStart, expectedEnd);
    expect(loadSignals).toHaveBeenLastCalledWith({
      window: 'custom',
      start_at: expectedStart,
      end_at: expectedEnd,
      workspace_query: '',
      agent_type: '',
      page: 1,
      page_size: 20,
    });
    expect(loadUsageSummary).toHaveBeenLastCalledWith('custom', '', expectedStart, expectedEnd);
    expect(loadRiskSummary).toHaveBeenLastCalledWith('custom', '', expectedStart, expectedEnd);
  });

  it('polls processing status while signal jobs are pending', async () => {
    appendDashboardSlots();
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadSignals = vi.fn(async () => signalPage);
    const loadUsageSummary = vi.fn(async () => usage);
    const loadRiskSummary = vi.fn(async () => risks);
    const loadProcessingStatus = vi
      .fn()
      .mockResolvedValueOnce(processingStatus)
      .mockResolvedValueOnce({ state: 'idle', counts: { pending: 0, running: 0, succeeded: 2, failed: 0 }, latest_failed: null });
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadSignals={loadSignals}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        loadProcessingStatus={loadProcessingStatus}
        onOpenSignal={() => {}}
      />
    );

    expect(await screen.findByLabelText('派生计算状态')).toHaveTextContent('派生计算：待处理');
    await waitFor(() => expect(screen.getByLabelText('派生计算状态')).toHaveTextContent('派生计算：空闲'), { timeout: 3000 });
  });
});

function appendDashboardSlots(): void {
  document.body.appendChild(Object.assign(document.createElement('div'), { id: 'dashboard-sidebar-slot' }));
  document.body.appendChild(Object.assign(document.createElement('div'), { id: 'dashboard-topbar-status-slot' }));
}
