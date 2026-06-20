import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { DashboardSummary, RiskSummary, StoriesResponse, UsageSummary } from '../api/types';
import { DashboardPage } from './DashboardPage';

const usage: UsageSummary = {
  window: '24h',
  totals: { associated_units: 1135, attributed_units: 2040, unknown_units: 1015 },
  rollups: [
    {
      rollup_id: '24h:session:session-001:associated:implementation',
      window: '24h',
      scope: 'session',
      scope_value: 'session-001',
      units: 1120,
      usage_kind: 'associated',
      activity_tag: 'implementation',
      additive: false,
      evidence_refs: ['proj-usage-associated-001']
    },
    {
      rollup_id: '24h:conversation:conversation-001:attributed:bug_fix',
      window: '24h',
      scope: 'conversation',
      scope_value: 'conversation-001',
      units: 2040,
      usage_kind: 'attributed',
      activity_tag: 'bug_fix',
      additive: true,
      evidence_refs: ['proj-usage-attributed-001']
    },
    {
      rollup_id: '24h:activity_tag:unknown:associated:unknown',
      window: '24h',
      scope: 'activity_tag',
      scope_value: 'unknown',
      units: 1015,
      usage_kind: 'associated',
      activity_tag: 'unknown',
      additive: false,
      evidence_refs: ['proj-usage-unknown-001']
    }
  ]
};

const risks: RiskSummary = {
  signals: [
    {
      risk_type: 'sensitive_object_touch',
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
      agent_version: '0.1.0',
      source_status: 'online',
      reason_code: 'run_once',
      policy_version: 1,
      last_heartbeat_at: '2026-06-19T11:30:03+08:00',
      outbox_backlog: 0,
      raw_upload_enabled: false,
      raw_upload_override: false,
      raw_upload_source: 'global_policy',
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
      summary: '采集器完成一次安全白名单自检，状态、游标和 outbox 已结构化上报。',
      occurred_at: '2026-06-19T11:30:03+08:00',
      source: 'codex',
      promoted_to_story: false
    }
    ]
  },
  stories: { total: 0, items: [] },
  risks: { total: 1, top: risks.signals }
};

const storyPage: StoriesResponse = { stories: [], total: 0, page: 1, page_size: 20, has_more: false };

describe('DashboardPage', () => {
  it('renders investigation summary instead of raw fact source counts', async () => {
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadStories = vi.fn(async () => storyPage);
    const loadUsageSummary = vi.fn(async () => usage);
    const loadRiskSummary = vi.fn(async () => risks);
    const onOpenFacts = vi.fn();
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadStories={loadStories}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        onOpenStory={() => {}}
        onOpenFacts={onOpenFacts}
      />
    );

    expect(await screen.findByLabelText('使用与风险治理')).toBeInTheDocument();
    expect(screen.getAllByText('windows-collector').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('事实来源')).not.toBeInTheDocument();
    expect(screen.getByText('排查摘要')).toBeInTheDocument();
    expect(screen.getByText(/风险 Top 项/)).toBeInTheDocument();
    expect(screen.getByText(/最近上报：采集器自检/)).toBeInTheDocument();
    expect(screen.getByText('1 / 6')).toBeInTheDocument();
    expect(screen.getByText(/当前没有需要人工处理的故事/)).toBeInTheDocument();
    expect(screen.getByText('1,135')).toBeInTheDocument();
    expect(screen.getByText('2,040')).toBeInTheDocument();
    expect(screen.getByText('1,015')).toBeInTheDocument();
    expect(screen.getByText(/Session：session-001 \/ 1,120/)).toBeInTheDocument();
    expect(screen.getByText(/Conversation：conversation-001 \/ 2,040/)).toBeInTheDocument();
    expect(screen.getByText(/未识别活动：1,015，关联/)).toBeInTheDocument();
    expect(screen.getAllByText(/敏感对象触达 \/ 配置：1,001/).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('button', { name: /筛选风险/ }));
    expect(onOpenFacts).toHaveBeenCalledWith({ fact_type: 'risk', window: '1h' });
    expect(loadStories).toHaveBeenCalledWith({ window: '1h', queue: 'actionable', page: 1, page_size: 20 });
    expect(loadUsageSummary).toHaveBeenCalledWith('1h');
    expect(loadRiskSummary).toHaveBeenCalledWith('1h');
    expect(loadDashboardSummary).toHaveBeenCalledWith('1h');
  });

  it('refreshes dashboard data without changing the selected time window', async () => {
    const user = userEvent.setup();
    const loadDashboardSummary = vi.fn(async () => summary);
    const loadStories = vi.fn(async () => storyPage);
    const loadUsageSummary = vi.fn(async () => usage);
    const loadRiskSummary = vi.fn(async () => risks);
    render(
      <DashboardPage
        loadDashboardSummary={loadDashboardSummary}
        loadStories={loadStories}
        loadUsageSummary={loadUsageSummary}
        loadRiskSummary={loadRiskSummary}
        onOpenStory={() => {}}
      />
    );

    await screen.findByText('排查摘要');
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
