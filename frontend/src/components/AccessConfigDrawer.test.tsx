import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { AccessConfigDrawer } from './AccessConfigDrawer';

const packageConfig = {
  filename: 'agent-observer-windows.zip',
  path: 'data/packages/agent-observer-windows.zip',
  sha256: 'abcdef1234567890',
  server_url: 'http://127.0.0.1:8765',
  agent_version: '0.3.0',
  protocol_version: 'agent-observer-telemetry/v3'
};

const policy = {
  policy_version: 1,
  raw_upload_mode: 'always_on' as const,
  enrichment_mode: 'enabled' as const,
  collection_interval_seconds: 5,
  max_events_per_cycle: 500,
  upload_batch_size: 100,
  worker_poll_interval_seconds: 10
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
        latest: '全局配置已保存，时间 2026-06-19T00:00:00+00:00',
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
    expect(screen.getByText('采集性能')).toBeInTheDocument();
    expect(screen.getByText('服务端处理')).toBeInTheDocument();
    expect(screen.getByText('采集内容')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '下载 Windows 客户端' })).toHaveAttribute(
      'href',
      '/api/client-package/windows'
    );

    expect(screen.getByText(/仅下载客户端时不需要保存全局配置/)).toBeInTheDocument();
    expect(screen.getByText('0.3.0')).toBeInTheDocument();
    expect(screen.getByText('agent-observer-telemetry/v3')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: '默认上传原始输入输出' })).not.toBeInTheDocument();
    expect(screen.getByText(/当前版本固定上传完整 Prompt 和响应内容/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText('采集间隔'));
    await user.type(screen.getByLabelText('采集间隔'), '8');
    await user.clear(screen.getByLabelText('单轮采集上限'));
    await user.type(screen.getByLabelText('单轮采集上限'), '900');
    await user.clear(screen.getByLabelText('上传批量'));
    await user.type(screen.getByLabelText('上传批量'), '120');
    await user.clear(screen.getByLabelText('Worker 轮询间隔'));
    await user.type(screen.getByLabelText('Worker 轮询间隔'), '12');
    await user.click(screen.getByLabelText('允许本机补证任务'));
    await user.click(screen.getByRole('button', { name: '保存并下发配置' }));

    await waitFor(() => expect(savePolicy).toHaveBeenCalled());
    expect(savePolicy).toHaveBeenCalledWith({
      expected_version: 1,
      enrichment_mode: 'disabled',
      collection_interval_seconds: 8,
      max_events_per_cycle: 900,
      upload_batch_size: 120,
      worker_poll_interval_seconds: 12
    });
    expect(await screen.findByText('全局配置已保存为 v2')).toBeInTheDocument();
    expect(screen.getByText(/全局配置已保存，时间/)).toBeInTheDocument();
  });

  it('restores performance defaults without changing enrichment mode', async () => {
    const user = userEvent.setup();
    render(
      <AccessConfigDrawer
        onClose={vi.fn()}
        loadConfig={vi.fn(async () => packageConfig)}
        loadPolicy={vi.fn(async () => ({
          ...policy,
          collection_interval_seconds: 30,
          max_events_per_cycle: 1000,
          upload_batch_size: 200,
          worker_poll_interval_seconds: 60
        }))}
        savePolicy={vi.fn(async () => policy)}
        loadAudit={vi.fn(async () => audit)}
        downloadUrl="/api/client-package/windows"
      />
    );

    expect(await screen.findByLabelText('采集间隔')).toHaveValue(30);
    await user.click(screen.getByRole('button', { name: '恢复默认值' }));

    expect(screen.getByLabelText('采集间隔')).toHaveValue(5);
    expect(screen.getByLabelText('单轮采集上限')).toHaveValue(500);
    expect(screen.getByLabelText('上传批量')).toHaveValue(100);
    expect(screen.getByLabelText('Worker 轮询间隔')).toHaveValue(10);
    expect(screen.getByLabelText('允许本机补证任务')).toBeChecked();
  });
});
