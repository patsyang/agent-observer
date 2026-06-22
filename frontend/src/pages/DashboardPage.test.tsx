import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DashboardSummary, RiskSummary, SignalsResponse, UsageSummary } from '../api/types';
import { DashboardPage } from './DashboardPage';

const usage: UsageSummary = {
  window: '24h',
  totals: {
    effective_units: 3175,
    unknown_units: 1015,
    cached_input_units: 900,
    input_token_units: 3000,
    cache_hit_rate: 0.3
  },
  trend: [
    { bucket: '2026-06-21T01:00:00+00:00', effective_units: 100, unknown_units: 0, cached_input_units: 20, input_token_units: 100, cache_hit_rate: 0.2 },
    { bucket: '2026-06-21T01:05:00+00:00', effective_units: 3075, unknown_units: 1015, cached_input_units: 880, input_token_units: 2900, cache_hit_rate: 0.3034 }
  ],
  rollups: [
    {
      rollup_id: '24h:session:session-001:implementation',
      window: '24h',
      scope: 'session',
      scope_value: 'session-001',
      units: 1120,
      activity_tag: 'implementation',
      evidence_refs: ['proj-usage-effective-001']
    },
    {
      rollup_id: '24h:conversation:conversation-001:bug_fix',
      window: '24h',
      scope: 'conversation',
      scope_value: 'conversation-001',
      units: 2040,
      activity_tag: 'bug_fix',
      evidence_refs: ['proj-usage-fix-001']
    },
    {
      rollup_id: '24h:activity_tag:unknown:unknown',
      window: '24h',
      scope: 'activity_tag',
      scope_value: 'unknown',
      units: 1015,
      activity_tag: 'unknown',
      evidence_refs: ['proj-usage-unknown-001']
    }
  ]
};

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
      agent_type: 'codex',
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      source_status: 'online',
      reason_code: 'run_once',
      policy_version: 1,
      last_heartbeat_at: '2026-06-19T11:30:03+08:00',
      outbox_backlog: 0,
      runtime_phase: 'uploading',
      last_seen_at: '2026-06-19T11:30:03+08:00',
      last_cycle_duration_ms: 3100,
      last_error: null
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

describe('DashboardPage', () => {
  afterEach(() => {
    document.getElementById('dashboard-sidebar-slot')?.remove();
  });

  it('renders signals and usage trend instead of usage anomaly investigation', async () => {
    document.body.appendChild(Object.assign(document.createElement('div'), { id: 'dashboard-sidebar-slot' }));
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadSignals = vi.fn(async () => signalPage);
    const loadUsageSummary = vi.fn(async () => usage);
    const loadRiskSummary = vi.fn(async () => risks);
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadSignals={loadSignals}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        onOpenSignal={() => {}}
      />
    );

    expect(await screen.findByLabelText('使用与风险治理')).toBeInTheDocument();
    expect(screen.getByLabelText('用量趋势')).toBeInTheDocument();
    expect(screen.getByTestId('usage-row')).toContainElement(screen.getByLabelText('用量趋势'));
    expect(screen.getByTestId('usage-row')).toContainElement(screen.getByLabelText('使用与风险治理'));
    expect(await screen.findByTestId('dashboard-sidebar-context')).toHaveTextContent('接入与筛选');
    expect(screen.getByLabelText('选择时间范围内真实消耗 token 与缓存命中 token 柱状图')).toBeInTheDocument();
    expect(screen.getAllByText('windows-collector').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('行为风险信号')).toBeInTheDocument();
    expect(screen.queryByText('行为风险信号台')).not.toBeInTheDocument();
    expect(screen.queryByText(/默认只看最近 1 小时/)).not.toBeInTheDocument();
    expect(screen.getByText('采集器自检')).toBeInTheDocument();
    expect(screen.queryByText(/最近命中：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/未上传原文/)).not.toBeInTheDocument();
    expect(screen.getByText('1 / 6')).toBeInTheDocument();
    expect(screen.getByText(/当前没有需要人工处理的信号/)).toBeInTheDocument();
    const governance = screen.getByLabelText('使用与风险治理');
    expect(within(governance).getByText('有效用量 (Token)')).toBeInTheDocument();
    expect(within(governance).getByText('缓存命中 (30.0%)')).toBeInTheDocument();
    expect(within(governance).getByText('待处理信号')).toBeInTheDocument();
    expect(within(governance).getByText('3,175')).toBeInTheDocument();
    expect(within(governance).getByText('900')).toBeInTheDocument();
    expect(within(governance).getByText('0')).toBeInTheDocument();
    expect(screen.getByText(/缓存 900（30.0%）/)).toBeInTheDocument();
    expect(within(governance).queryByText('未知活动')).not.toBeInTheDocument();
    expect(within(governance).queryByText('模型调用有效 token')).not.toBeInTheDocument();
    expect(within(governance).queryByText('当前队列待看')).not.toBeInTheDocument();
    expect(within(governance).queryByText(/活动：/)).not.toBeInTheDocument();
    expect(within(governance).queryByText(/风险：/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('筛选工作区')).toBeInTheDocument();
    expect(loadSignals).toHaveBeenCalledWith({ window: '1h', workspace_query: '', page: 1, page_size: 20 });
    expect(loadUsageSummary).toHaveBeenCalledWith('1h');
    expect(loadRiskSummary).toHaveBeenCalledWith('1h');
    expect(loadDashboardSummary).toHaveBeenCalledWith('1h');
  });

  it('refreshes dashboard data without changing the selected time window', async () => {
    const user = userEvent.setup();
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadSignals = vi.fn(async () => signalPage);
    const loadUsageSummary = vi.fn(async () => usage);
    const loadRiskSummary = vi.fn(async () => risks);
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadSignals={loadSignals}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        onOpenSignal={() => {}}
      />
    );

    await screen.findByText('行为风险信号');
    await user.click(screen.getByRole('button', { name: '24小时' }));
    await waitFor(() => expect(loadDashboardSummary).toHaveBeenLastCalledWith('24h'));
    expect(loadRiskSummary).toHaveBeenLastCalledWith('24h');
    await user.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(loadDashboardSummary).toHaveBeenLastCalledWith('24h'));
    expect(loadRiskSummary).toHaveBeenLastCalledWith('24h');
    expect(loadDashboardSummary).toHaveBeenCalledTimes(3);
    expect(loadRiskSummary).toHaveBeenCalledTimes(3);
    expect(screen.getByText(/最后刷新/)).toBeInTheDocument();
  });
});
