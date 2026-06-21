import { expect, test } from '@playwright/test';

test('public onboarding shows registered online collector and package download', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const workstationName = `e2e-workstation-${suffix}`;
  const registered = await request.post('http://127.0.0.1:8765/api/collectors/register', {
    data: {
      collector_id: `collector-onboarding-${suffix}`,
      display_name: workstationName,
      hostname: workstationName,
      windows_username: 'synthetic-user',
      agent_type: 'codex',
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0'
    }
  });
  expect(registered.ok()).toBeTruthy();
  const collector = await registered.json();
  const heartbeat = await request.post(
    `http://127.0.0.1:8765/api/collectors/${collector.collector_id}/heartbeat`,
    {
      data: {
        protocol_version: 'agent-observer-telemetry/v2',
        agent_version: '0.2.0',
        source_status: 'online',
        reason_code: 'online',
        outbox_backlog: 0
      }
    }
  );
  expect(heartbeat.ok()).toBeTruthy();
  const staleId = `stale-e2e-${Date.now()}`;
  const staleName = `Stale E2E collector ${staleId}`;
  const stale = await request.post('http://127.0.0.1:8765/api/collectors/register', {
    data: {
      collector_id: staleId,
      display_name: staleName,
      hostname: 'stale-e2e-workstation',
      windows_username: 'synthetic-user',
      agent_type: 'codex',
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      source_status: 'offline',
      reason_code: 'heartbeat_stale'
    }
  });
  expect(stale.ok()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '观测总览' })).toBeVisible();
  await expect(page.getByText(/login/i)).toHaveCount(0);
  await page.getByRole('button', { name: /采集器 状态与策略/ }).click();
  await expect(page.getByRole('heading', { level: 1, name: '采集器' })).toBeVisible({ timeout: 15000 });
  const row = page.getByRole('row').filter({ hasText: workstationName });
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row.getByRole('cell', { name: '在线', exact: true })).toBeVisible();
  await expect(row.getByRole('cell', { name: /^v\d+$/ })).toBeVisible();
  await expect(row.getByRole('cell', { name: /已开启/ })).toBeVisible();
  await expect(row.getByRole('checkbox', { name: /原文上报/ })).toHaveCount(0);
  await expect(row.getByRole('button', { name: /清理/ })).toBeDisabled();

  const staleRow = page.getByRole('row').filter({ hasText: staleId });
  await expect(staleRow).toBeVisible({ timeout: 15000 });
  await staleRow.getByRole('button', { name: `清理 ${staleName}` }).click();
  await expect(page.getByText(`已清理 ${staleName}`)).toBeVisible({ timeout: 15000 });
  await expect(staleRow).toHaveCount(0);

  await page.getByRole('button', { name: '接入配置' }).click();
  await expect(page.getByRole('link', { name: '下载 Windows 客户端' })).toBeVisible({ timeout: 15000 });
});
