import { expect, test } from '@playwright/test';

import { E2E_API_BASE } from './support/urls';

test('operator reviews behavior risk signals with grouped evidence', async ({ page, request }) => {
  const suffix = Date.now();
  const conversation = `conversation-e2e-signal-${suffix}`;
  const items = [
    {
      source_event_id: `signal-error-${suffix}`,
      fact_type: 'error',
      category: 'codex_error',
      quality: 'high',
      severity: 'high',
      summary: 'function_call_output failed with exit_code=1',
      occurred_at: new Date().toISOString(),
      span: 'tool:error',
      raw_hash: `hash-error-${suffix}`,
      projection: { tool_name: 'exec_command', exit_code: 1 },
      error_signature: { signature_key: `sig-${suffix}`, category: 'codex_error' },
      source_refs: { conversation_ref: conversation },
      source_specific: { codex_event_type: 'tool_result' }
    },
    {
      source_event_id: `signal-key-${suffix}`,
      fact_type: 'risk',
      category: 'high_risk_operation',
      quality: 'high',
      severity: 'medium',
      summary: 'changed .gitignore',
      occurred_at: new Date().toISOString(),
      span: 'tool:key-file',
      raw_hash: `hash-key-${suffix}`,
      projection: { object_type: 'configuration', path: '.gitignore' },
      risk: { risk_type: 'high_risk_operation', severity: 'medium', object_type: 'configuration' },
      source_refs: { conversation_ref: conversation },
      source_specific: { codex_event_type: 'tool_result' }
    },
    ...Array.from({ length: 20 }, (_, index) => ({
      source_event_id: `signal-workspace-${suffix}-${index}`,
      fact_type: 'risk',
      category: 'high_risk_operation',
      quality: 'high',
      severity: 'medium',
      summary: `workspace file changed src/file_${index}.py`,
      occurred_at: new Date().toISOString(),
      span: `tool:workspace:${index}`,
      raw_hash: `hash-workspace-${suffix}-${index}`,
      projection: { object_type: 'workspace_file', path: `src/file_${index}.py` },
      risk: { risk_type: 'high_risk_operation', severity: 'medium', object_type: 'workspace_file' },
      source_refs: { conversation_ref: conversation },
      source_specific: { codex_event_type: 'tool_result' }
    }))
  ];

  await request.post(`${E2E_API_BASE}/api/telemetry/ingest`, {
    data: {
      batch_id: `signal-e2e-${suffix}`,
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      collector_id: 'signal-e2e',
      source: 'codex',
      cursor: `cursor-${suffix}`,
      items
    }
  });
  const rebuilt = await request.post(`${E2E_API_BASE}/api/signals/rebuild`, { data: { reason: 'e2e-signal' } });
  const body = await rebuilt.json();
  expect(body.signals.some((item: { signal_kind: string }) => item.signal_kind === 'tool_failure_cluster')).toBeTruthy();
  expect(body.signals.some((item: { signal_kind: string }) => item.signal_kind === 'workspace_change_burst')).toBeTruthy();
  expect(body.signals.some((item: { signal_kind: string }) => item.signal_kind === 'key_file_change')).toBeTruthy();

  await page.goto('/');
  const failureCard = page.locator('[data-signal-key^="tool_failure_cluster"]').first();
  await expect(failureCard).toBeVisible({ timeout: 15000 });
  await failureCard.getByTestId('open-signal').click();
  await expect(page.getByTestId('signal-detail')).toBeVisible();
  await expect(page.getByTestId('evidence-groups')).toContainText('会话');
  await expect(page.getByTestId('evidence-groups')).not.toContainText('N 行');
});
