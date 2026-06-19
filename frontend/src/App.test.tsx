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
        if (url.includes('/api/facts')) {
          return Response.json({ facts: [] });
        }
        if (url.includes('/api/stories')) {
          return Response.json({ stories: [] });
        }
        if (url.includes('/api/usage/summary')) {
          return Response.json({
            window: '24h',
            rollups: [],
            totals: { associated_units: 0, attributed_units: 0, unknown_units: 0 }
          });
        }
        if (url.includes('/api/risks/summary')) {
          return Response.json({ signals: [] });
        }
        if (url.endsWith('/api/policy')) {
          return Response.json({
            policy_version: 1,
            template_enabled: true,
            upload_raw: false,
            collection_policy: 'codex default local observation',
            diagnostic_policy: 'whitelist only'
          });
        }
        if (url.endsWith('/api/audit/recent')) {
          return Response.json({ latest: '暂无审计记录', events: [] });
        }
        return Response.json({
          filename: 'agent-observer-windows.zip',
          path: 'data/packages/agent-observer-windows.zip',
          config_path: 'data/packages/agent-observer.config.json',
          sha256: '1234567890abcdef'
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
