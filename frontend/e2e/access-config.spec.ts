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
  await expect(page.getByText(`v${policy.policy_version}`)).toBeVisible();
  await expect(page.getByText(/仅下载客户端时不需要保存接入策略/)).toBeVisible();

  await expect(page.getByText(/在线客户端会在下一次心跳后拉取最新策略/)).toBeVisible();
  await expect(page.getByText(/当前版本固定上传完整 Prompt 和响应内容/)).toBeVisible();
  await expect(page.getByLabel('默认上传原始输入输出')).toHaveCount(0);
  await page.getByLabel('允许本机补证任务').click();
  await page.getByRole('button', { name: '保存接入策略' }).click();

  await expect(page.getByRole('status')).toContainText(`接入策略已保存为 v${policy.policy_version + 1}`);
  await expect(page.getByText('最近审计')).toBeVisible();

  const after = await request.get('http://127.0.0.1:8765/api/policy');
  expect(after.ok()).toBeTruthy();
  const updated = await after.json();
  expect(updated.policy_version).toBe(policy.policy_version + 1);
  expect(updated.raw_upload_mode).toBe('always_on');
  expect(updated.enrichment_mode).toBe(policy.enrichment_mode === 'enabled' ? 'disabled' : 'enabled');
});
