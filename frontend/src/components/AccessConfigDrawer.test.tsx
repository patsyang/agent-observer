import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AccessConfigDrawer } from './AccessConfigDrawer';

const packageConfig = {
  filename: 'agent-observer-windows.zip',
  path: 'data/packages/agent-observer-windows.zip',
  config_path: 'data/packages/agent-observer.config.json',
  sha256: 'abcdef1234567890'
};

const policy = {
  policy_version: 1,
  template_enabled: true,
  upload_raw: false,
  collection_policy: 'codex default local observation',
  diagnostic_policy: 'whitelist only'
};

const audit = {
  latest: '暂无审计记录',
  events: []
};

describe('AccessConfigDrawer', () => {
  it('loads package, policy, saves changes and displays audit feedback', async () => {
    const user = userEvent.setup();
    const savePolicy = vi.fn(async () => ({ ...policy, policy_version: 2, template_enabled: false, upload_raw: true }));
    const loadAudit = vi
      .fn()
      .mockResolvedValueOnce(audit)
      .mockResolvedValueOnce({
        latest: 'policy_changed by fixed-management-account at 2026-06-19T00:00:00+00:00',
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
    expect(screen.getByText('策略开关')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '下载 Windows 客户端' })).toHaveAttribute(
      'href',
      '/api/client-package/windows'
    );

    await user.click(screen.getByLabelText('启用 Codex 来源模板'));
    expect(screen.getByText(/仅下载客户端时不需要点击/)).toBeInTheDocument();
    expect(screen.getByText(/在线客户端可在采集器管理中单独开关/)).toBeInTheDocument();
    await user.click(screen.getByLabelText('客户端下载默认上传原文'));
    await user.clear(screen.getByLabelText('采集策略'));
    await user.type(screen.getByLabelText('采集策略'), 'codex deterministic events only');
    await user.click(screen.getByRole('button', { name: '保存策略' }));

    await waitFor(() => expect(savePolicy).toHaveBeenCalled());
    expect(savePolicy).toHaveBeenCalledWith({
      expected_version: 1,
      template_enabled: false,
      upload_raw: true,
      collection_policy: 'codex deterministic events only',
      diagnostic_policy: 'whitelist only'
    });
    expect(await screen.findByText('策略已保存为 v2')).toBeInTheDocument();
    expect(screen.getByText(/policy_changed by fixed-management-account/)).toBeInTheDocument();
  });
});
