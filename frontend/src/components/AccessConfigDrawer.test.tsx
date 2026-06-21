import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AccessConfigDrawer } from './AccessConfigDrawer';

const packageConfig = {
  filename: 'agent-observer-windows.zip',
  path: 'data/packages/agent-observer-windows.zip',
  sha256: 'abcdef1234567890',
  server_url: 'http://127.0.0.1:8765',
  agent_version: '0.2.0',
  protocol_version: 'agent-observer-telemetry/v2'
};

const policy = {
  policy_version: 1,
  raw_upload_mode: 'always_on' as const,
  enrichment_mode: 'enabled' as const
};

const audit = {
  latest: '暂无审计记录',
  events: []
};

describe('AccessConfigDrawer', () => {
  it('loads package, policy, saves changes and displays audit feedback', async () => {
    const user = userEvent.setup();
    const savePolicy = vi.fn(async () => ({ ...policy, policy_version: 2, enrichment_mode: 'disabled' as const }));
    const loadAudit = vi
      .fn()
      .mockResolvedValueOnce(audit)
      .mockResolvedValueOnce({
        latest: '接入策略已保存，时间 2026-06-19T00:00:00+00:00',
        events: []
      });

    render(
      <AccessConfigDrawer
        onClose={vi.fn()}
        loadConfig={vi.fn(async () => packageConfig)}
        loadPolicy={vi.fn(async () => policy)}
        savePolicy={savePolicy}
        loadAudit={loadAudit}
        downloadUrl="/api/client-package/windows"
      />
    );

    expect(await screen.findByText('Windows collector 客户端')).toBeInTheDocument();
    expect(screen.getByText('采集内容')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '下载 Windows 客户端' })).toHaveAttribute(
      'href',
      '/api/client-package/windows'
    );

    expect(screen.getByText(/仅下载客户端时不需要保存接入策略/)).toBeInTheDocument();
    expect(screen.getByText('0.2.0')).toBeInTheDocument();
    expect(screen.getByText('agent-observer-telemetry/v2')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: '默认上传原始输入输出' })).not.toBeInTheDocument();
    expect(screen.getByText(/当前版本固定上传完整 Prompt 和响应内容/)).toBeInTheDocument();
    await user.click(screen.getByLabelText('允许本机补证任务'));
    await user.click(screen.getByRole('button', { name: '保存接入策略' }));

    await waitFor(() => expect(savePolicy).toHaveBeenCalled());
    expect(savePolicy).toHaveBeenCalledWith({
      expected_version: 1,
      enrichment_mode: 'disabled'
    });
    expect(await screen.findByText('接入策略已保存为 v2')).toBeInTheDocument();
    expect(screen.getByText(/接入策略已保存，时间/)).toBeInTheDocument();
  });
});
