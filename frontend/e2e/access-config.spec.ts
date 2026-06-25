import { expect, test } from '@playwright/test';
import { E2E_API_BASE } from './support/urls';

test('public access config downloads client and updates policy with audit feedback', async ({ page, request }) => {
  const before = await request.get(`${E2E_API_BASE}/api/policy`);
  expect(before.ok()).toBeTruthy();
  const policy = await before.json();

  await page.goto('/');
  await expect(page.getByTestId('dashboard-page')).toBeVisible();
  await expect(page.getByText(/login/i)).toHaveCount(0);

  await page.getByTestId('open-access-config').click();
  await expect(page.getByTestId('access-config-drawer')).toBeVisible();
  await expect(page.getByTestId('download-client')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('download-client')).toHaveAttribute('href', /\/api\/client-package\/windows$/);
  await expect(page.getByText(`v${policy.policy_version}`)).toBeVisible();
  await expect(page.getByLabel('默认上传原始输入输出')).toHaveCount(0);
  await page.getByLabel('采集间隔').fill('8');
  await page.getByLabel('单轮采集上限').fill('900');
  await page.getByLabel('上传批量').fill('120');
  await page.getByLabel('Worker 轮询间隔').fill('12');
  await page.getByLabel('允许本机补证任务').click();
  await page.getByTestId('save-policy').click();

  await expect(page.getByRole('status')).toContainText(`全局配置已保存为 v${policy.policy_version + 1}`);

  const audit = await request.get(`${E2E_API_BASE}/api/audit/recent`);
  expect(audit.ok()).toBeTruthy();
  const auditBody = await audit.json();
  expect(auditBody.events[0].action).toBe('policy_changed');
  await expect(page.getByTestId('access-audit')).toContainText(auditBody.latest);

  const after = await request.get(`${E2E_API_BASE}/api/policy`);
  expect(after.ok()).toBeTruthy();
  const updated = await after.json();
  expect(updated.policy_version).toBe(policy.policy_version + 1);
  expect(updated.raw_upload_mode).toBe('always_on');
  expect(updated.enrichment_mode).toBe(policy.enrichment_mode === 'enabled' ? 'disabled' : 'enabled');
  expect(updated.collection_interval_seconds).toBe(8);
  expect(updated.max_events_per_cycle).toBe(900);
  expect(updated.upload_batch_size).toBe(120);
  expect(updated.worker_poll_interval_seconds).toBe(12);

  await page.reload();
  await page.getByTestId('open-access-config').click();
  await expect(page.getByLabel('采集间隔')).toHaveValue('8');
  await expect(page.getByLabel('单轮采集上限')).toHaveValue('900');
  await expect(page.getByLabel('上传批量')).toHaveValue('120');
  await expect(page.getByLabel('Worker 轮询间隔')).toHaveValue('12');
});
