import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { App } from './App';

describe('App shell', () => {
  it('navigates to collectors and opens access config without login', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.endsWith('/api/collectors')) {
          return Response.json({ collectors: [] });
        }
        if (url.includes('/api/dashboard/summary')) {
          return Response.json({
            window: '1h',
            collectors: { total: 0, online: 0, degraded: 0, offline: 0, items: [] },
            facts: { total: 0, items: [] },
            signals: { total: 0, items: [] },
            risks: { total: 0, top: [] }
          });
        }
        if (url.includes('/api/conversations')) {
          return Response.json({ conversations: [], total: 0, page: 1, page_size: 50, has_more: false, window: '1h' });
        }
        if (url.includes('/api/signals')) {
          return Response.json({ signals: [] });
        }
        if (url.includes('/api/usage/summary')) {
          return Response.json({
            window: '24h',
            rollups: [],
            trend: [],
            totals: {
              effective_units: 0,
              unknown_units: 0,
              cached_input_units: 0,
              input_token_units: 0,
              output_token_units: 0,
              total_token_units: 0,
              cache_write_input_units: 0,
              reasoning_output_units: 0,
              credit_total: 0,
              cache_observed_input_units: 0,
              cache_hit_rate: 0
            }
          });
        }
        if (url.includes('/api/risks/summary')) {
          return Response.json({ signals: [] });
        }
        if (url.endsWith('/api/policy')) {
          return Response.json({
            policy_version: 1,
            raw_upload_mode: 'always_on',
            enrichment_mode: 'enabled',
            collection_interval_seconds: 5,
            max_events_per_cycle: 500,
            upload_batch_size: 100
          });
        }
        if (url.endsWith('/api/audit/recent')) {
          return Response.json({ latest: '暂无审计记录', events: [] });
        }
        return Response.json({
          filename: 'agent-observer-windows.zip',
          path: 'data/packages/agent-observer-windows.zip',
          sha256: '1234567890abcdef',
          server_url: 'http://127.0.0.1:8765',
          agent_version: '0.3.0',
          protocol_version: 'agent-observer-telemetry/v3'
        });
      })
    );
    const user = userEvent.setup();
    render(<App />);

    const nav = screen.getByRole('navigation', { name: '主导航' });
    await user.click(within(nav).getByRole('button', { name: /采集器 状态与策略/ }));
    expect(await screen.findByText('还没有采集器注册。请从“下载与策略配置”下载 Windows 包并运行 start。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '接入配置' }));
    expect(await screen.findByLabelText('下载与策略配置')).toBeInTheDocument();
    expect(screen.queryByText(/login/i)).not.toBeInTheDocument();
  });
});
