import { expect, test } from '@playwright/test';

test('public access config downloads client and updates policy with audit feedback', async ({ page, request }) => {
  const before = await request.get('http://127.0.0.1:8765/api/policy');
  expect(before.ok()).toBeTruthy();
  const policy = await before.json();

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '观测总览' })).toBeVisible();
  await expect(page.getByText(/login/i)).toHaveCount(0);

  await page.getByRole('button', { name: '接入配置' }).click();
  await expect(page.getByRole('heading', { name: 'Windows collector 客户端' })).toBeVisible();
  await expect(page.getByRole('link', { name: '下载 Windows 客户端' })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('http://127.0.0.1:8765')).toBeVisible();
  await expect(page.getByText('服务端 effective_policy')).toBeVisible();
  await expect(page.getByText(`v${policy.policy_version}`)).toBeVisible();
  await expect(page.getByText(/仅下载客户端时不需要点击/)).toBeVisible();

  await expect(page.getByText(/在线客户端可在采集器管理中单独开关/)).toBeVisible();
  const uploadRaw = page.getByLabel('客户端下载默认上传原文');
  if ((await uploadRaw.isChecked()) === Boolean(policy.upload_raw)) {
    await uploadRaw.click();
  }
  await page.getByLabel('采集策略').fill('codex deterministic events only');
  await page.getByLabel('诊断策略').fill('queue whitelist diagnostics when offline');
  await page.getByRole('button', { name: '保存策略' }).click();

  await expect(page.getByRole('status')).toContainText(`策略已保存为 v${policy.policy_version + 1}`);
  await expect(page.getByText('最近审计')).toBeVisible();

  const after = await request.get('http://127.0.0.1:8765/api/policy');
  expect(after.ok()).toBeTruthy();
  const updated = await after.json();
  expect(updated.policy_version).toBe(policy.policy_version + 1);
  expect(updated.collection_policy).toBe('codex deterministic events only');
  expect(updated.diagnostic_policy).toBe('queue whitelist diagnostics when offline');
});
