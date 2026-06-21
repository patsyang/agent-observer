import { expect, test } from '@playwright/test';

test('operator views usage and governance trend after fixture ingestion', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const sessionId = `session-e2e-${suffix}`;
  const conversationId = `conversation-e2e-${suffix}`;
  const ingest = await request.post('http://127.0.0.1:8765/api/telemetry/ingest', {
    data: {
      batch_id: 'e2e-governance-001',
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      collector_id: 'collector-codex',
      source: 'codex',
      cursor: 'cursor-governance-001',
      items: [
        {
          source_event_id: `e2e-usage-implementation-${suffix}`,
          fact_type: 'usage',
          category: 'usage',
          quality: 'high',
          severity: 'low',
          summary: 'E2E implementation usage',
          occurred_at: new Date().toISOString(),
          span: 'session:e2e',
          raw_hash: 'hash-e2e-usage-implementation',
          projection: { activity_tag: 'implementation', units: 120 },
          usage: {
            units: 120,
            activity_tag: 'implementation',
            session_id: sessionId,
            conversation_id: conversationId,
            project_ref: 'project-agent-observer',
            account_ref: 'account-local'
          },
          source_refs: { conversation_ref: conversationId },
          source_specific: { codex_event_type: 'usage_summary' }
        },
        {
          source_event_id: `e2e-usage-fix-${suffix}`,
          fact_type: 'usage',
          category: 'usage',
          quality: 'high',
          severity: 'low',
          summary: 'E2E fix usage',
          occurred_at: new Date().toISOString(),
          span: 'conversation:e2e',
          raw_hash: 'hash-e2e-usage-fix',
          projection: { activity_tag: 'bug_fix', units: 40 },
          usage: {
            units: 40,
            activity_tag: 'bug_fix',
            session_id: sessionId,
            conversation_id: conversationId,
            project_ref: 'project-agent-observer',
            account_ref: 'account-local'
          },
          source_refs: { conversation_ref: conversationId },
          source_specific: { codex_event_type: 'usage_summary' }
        },
        {
          source_event_id: `e2e-risk-sensitive-${suffix}`,
          fact_type: 'risk',
          category: 'sensitive_touch',
          quality: 'high',
          severity: 'high',
          summary: 'E2E sensitive configuration touched',
          occurred_at: new Date().toISOString(),
          span: 'session:e2e',
          raw_hash: 'hash-e2e-risk-sensitive',
          projection: { object_type: 'configuration', count: 1 },
          risk: {
            risk_type: 'sensitive_object_touch',
            severity: 'high',
            object_type: 'configuration'
          },
          source_refs: { conversation_ref: conversationId },
          source_specific: { codex_event_type: 'tool_result' }
        }
      ]
    }
  });
  expect(ingest.ok()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByLabel('观测信号运营台')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('region', { name: '用量趋势' })).toBeVisible({ timeout: 15000 });
  await expect(page.getByLabel('使用与风险治理')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.metric').filter({ hasText: '有效用量' })).toBeVisible();
  await expect(page.locator('.metric').filter({ hasText: '缓存命中' })).toBeVisible();
  await expect(page.getByLabel('使用与风险治理').getByText(/敏感对象触达 \/ 配置/)).toBeVisible();

  const usage = await request.get('http://127.0.0.1:8765/api/usage/summary');
  const usageBody = await usage.json();
  expect(usageBody.rollups.some((row: { scope: string; scope_value: string; units: number }) => (
    row.scope === 'session' && row.scope_value === sessionId && row.units === 160
  ))).toBeTruthy();
  expect(usageBody.rollups.some((row: { scope: string; scope_value: string; units: number }) => (
    row.scope === 'conversation' && row.scope_value === conversationId && row.units === 160
  ))).toBeTruthy();
  expect(usageBody.rollups.some((row: { scope: string; scope_value: string; units: number }) => (
    row.scope === 'activity_tag' && row.scope_value === 'implementation' && row.units >= 120
  ))).toBeTruthy();
  expect(usageBody.rollups.some((row: { scope: string; scope_value: string; units: number }) => (
    row.scope === 'activity_tag' && row.scope_value === 'bug_fix' && row.units >= 40
  ))).toBeTruthy();
  const risks = await request.get('http://127.0.0.1:8765/api/risks/summary');
  const riskBody = await risks.json();
  expect(riskBody.signals[0].object_type).toBe('configuration');
});
