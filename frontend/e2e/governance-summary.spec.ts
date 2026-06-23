import { expect, test } from '@playwright/test';
import { E2E_API_BASE } from './support/urls';

test('operator views usage and governance trend after fixture ingestion', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const sessionId = `session-e2e-${suffix}`;
  const conversationId = `conversation-e2e-${suffix}`;
  const ingest = await request.post(`${E2E_API_BASE}/api/telemetry/ingest`, {
    data: {
      batch_id: 'e2e-governance-001',
      protocol_version: 'agent-observer-telemetry/v3',
      agent_version: '0.3.0',
      collector_id: 'collector-codex',
      source: 'codex',
      source_id: 'codex-local',
      agent_type: 'codex',
      source_kind: 'codex_local',
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
          source_specific: { event_type: 'usage_summary' }
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
          source_specific: { event_type: 'usage_summary' }
        },
        {
          source_event_id: `e2e-risk-sensitive-${suffix}`,
          fact_type: 'risk',
          category: 'sensitive_content_exposure',
          quality: 'high',
          severity: 'high',
          summary: 'E2E sensitive configuration touched',
          occurred_at: new Date().toISOString(),
          span: 'session:e2e',
          raw_hash: 'hash-e2e-risk-sensitive',
          projection: { object_type: 'configuration', count: 1 },
          risk: {
            risk_type: 'sensitive_content_exposure',
            severity: 'high',
            object_type: 'configuration'
          },
          source_refs: { conversation_ref: conversationId },
          source_specific: { event_type: 'tool_result' }
        }
      ]
    }
  });
  expect(ingest.ok()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByTestId('dashboard-page')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('usage-trend')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('usage-row')).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('有效用量 (Token)')).toBeVisible();
  await expect(page.getByTestId('signal-queue')).toBeVisible();

  const usage = await request.get(`${E2E_API_BASE}/api/usage/summary`);
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
  const risks = await request.get(`${E2E_API_BASE}/api/risks/summary`);
  const riskBody = await risks.json();
  expect(riskBody.signals[0].object_type).toBe('configuration');
});
