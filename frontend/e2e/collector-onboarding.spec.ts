import { expect, test } from '@playwright/test';
import { E2E_API_BASE } from './support/urls';

const sources = [
  {
    source_id: 'codex-local',
    agent_type: 'codex',
    source_kind: 'codex_local',
    display_name: 'Codex Local',
    source_status: 'online',
    reason_code: 'online'
  },
  {
    source_id: 'workbuddy-local',
    agent_type: 'workbuddy',
    source_kind: 'workbuddy_local',
    display_name: 'WorkBuddy Local',
    source_status: 'online',
    reason_code: 'online'
  }
];

test('public onboarding shows registered online collector and package download', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const workstationName = `e2e-workstation-${suffix}`;
  const registered = await request.post(`${E2E_API_BASE}/api/collectors/register`, {
    data: {
      collector_id: `collector-onboarding-${suffix}`,
      display_name: workstationName,
      hostname: workstationName,
      windows_username: 'synthetic-user',
      agent_type: 'codex',
      protocol_version: 'agent-observer-telemetry/v3',
      agent_version: '0.3.0',
      sources
    }
  });
  expect(registered.ok()).toBeTruthy();
  const collector = await registered.json();
  const heartbeat = await request.post(
    `${E2E_API_BASE}/api/collectors/${collector.collector_id}/heartbeat`,
    {
      data: {
        protocol_version: 'agent-observer-telemetry/v3',
        agent_version: '0.3.0',
        source_status: 'online',
        reason_code: 'online',
        outbox_backlog: 0,
        sources
      }
    }
  );
  expect(heartbeat.ok()).toBeTruthy();
  const staleId = `stale-e2e-${Date.now()}`;
  const staleName = `Stale E2E collector ${staleId}`;
  const stale = await request.post(`${E2E_API_BASE}/api/collectors/register`, {
    data: {
      collector_id: staleId,
      display_name: staleName,
      hostname: 'stale-e2e-workstation',
      windows_username: 'synthetic-user',
      agent_type: 'codex',
      protocol_version: 'agent-observer-telemetry/v3',
      agent_version: '0.3.0',
      source_status: 'offline',
      reason_code: 'heartbeat_stale',
      sources
    }
  });
  expect(stale.ok()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByTestId('dashboard-page')).toBeVisible();
  await expect(page.getByText(/login/i)).toHaveCount(0);
  await page.getByTestId('nav-collectors').click();
  await expect(page.getByTestId('collectors-page')).toBeVisible({ timeout: 15000 });
  const row = page.locator(`[data-collector-id="${collector.collector_id}"]`);
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row).toContainText(workstationName);
  await expect(row.getByRole('checkbox', { name: /原文上报/ })).toHaveCount(0);
  await expect(row.getByTestId('cleanup-collector')).toBeDisabled();

  const staleRow = page.locator(`[data-collector-id="${staleId}"]`);
  await expect(staleRow).toBeVisible({ timeout: 15000 });
  await staleRow.getByTestId('cleanup-collector').click();
  await expect(page.getByText(`已清理 ${staleName}`)).toBeVisible({ timeout: 15000 });
  await expect(staleRow).toHaveCount(0);

  await page.getByTestId('open-access-config').click();
  await expect(page.getByTestId('download-client')).toBeVisible({ timeout: 15000 });
});
