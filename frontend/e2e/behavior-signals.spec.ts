import { expect, test } from '@playwright/test';

import { E2E_API_BASE } from './support/urls';

test('operator reviews behavior risk signals with grouped evidence', async ({ page, request }) => {
  const suffix = Date.now();
  const conversation = `conversation-e2e-signal-${suffix}`;
  const sessionTitle = 'E2E 工具失败排查';
  const command = 'cmd /c apps\\agent-observer\\scripts\\start-backend.cmd';
  const error = 'Port 8765 is already in use';
  const sourceRefs = { conversation_ref: conversation, session_title: sessionTitle };
  const toolFailures = Array.from({ length: 3 }, (_, index) => ({
    source_event_id: `signal-error-${suffix}-${index}`,
    fact_type: 'error',
    category: 'tool_execution_failure',
    quality: 'high',
    severity: 'high',
    summary: `function_call_output failed with exit_code=1 (${index})`,
    occurred_at: new Date(Date.now() - index * 1000).toISOString(),
    span: `tool:error:${index}`,
    raw_hash: `hash-error-${suffix}-${index}`,
    projection: {
      tool_name: 'exec_command',
      call_id: `call-e2e-${index}`,
      command,
      command_excerpt: command,
      command_category: 'shell',
      exit_code: 1,
      error_excerpt: error,
      wall_time_seconds: 1.2
    },
    error_signature: { signature_key: `tool-exec-failure-${suffix}-${index}`, category: 'tool_execution_failure' },
    source_refs: sourceRefs,
    source_specific: { codex_event_type: 'tool_result' }
  }));
  const items = [
    ...toolFailures,
    {
      source_event_id: `signal-key-${suffix}`,
      fact_type: 'risk',
      category: 'file_change',
      quality: 'high',
      severity: 'medium',
      summary: 'changed .gitignore',
      occurred_at: new Date().toISOString(),
      span: 'tool:key-file',
      raw_hash: `hash-key-${suffix}`,
      projection: { object_type: 'configuration', changed_paths: ['.gitignore'], file_count: 1, additions: 1, deletions: 0 },
      risk: { risk_type: 'file_change', severity: 'medium', object_type: 'configuration' },
      source_refs: sourceRefs,
      source_specific: { codex_event_type: 'tool_result' }
    },
    ...Array.from({ length: 20 }, (_, index) => ({
      source_event_id: `signal-workspace-${suffix}-${index}`,
      fact_type: 'risk',
      category: 'file_change',
      quality: 'high',
      severity: 'medium',
      summary: `workspace file changed src/file_${index}.py`,
      occurred_at: new Date().toISOString(),
      span: `tool:workspace:${index}`,
      raw_hash: `hash-workspace-${suffix}-${index}`,
      projection: { object_type: 'workspace_file', changed_paths: [`src/file_${index}.py`], file_count: 1, additions: 30, deletions: 0 },
      risk: { risk_type: 'file_change', severity: 'medium', object_type: 'workspace_file' },
      source_refs: sourceRefs,
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
  const toolSignals = body.signals.filter((item: { signal_kind: string }) => item.signal_kind === 'tool_execution_failure');
  expect(toolSignals).toHaveLength(1);
  expect(toolSignals[0].occurrence_count).toBe(3);
  expect(body.signals.some((item: { signal_kind: string }) => item.signal_kind === 'change_volume_anomaly')).toBeTruthy();
  expect(body.signals.some((item: { signal_kind: string }) => item.signal_kind === 'key_file_change')).toBeTruthy();

  await page.goto('/');
  const failureCard = page.locator('[data-signal-key^="tool_execution_failure"]').first();
  await expect(failureCard).toBeVisible({ timeout: 15000 });
  await expect(failureCard).toContainText('本会话 3 次 exec_command 执行失败，退出码 1');
  await expect(failureCard).toContainText(sessionTitle);
  await expect(failureCard).toContainText(command);
  await failureCard.getByTestId('open-signal').click();
  await expect(page.getByTestId('signal-detail')).toBeVisible();
  await expect(page.getByTestId('evidence-groups')).toContainText('命中事件');
  await expect(page.getByTestId('evidence-groups')).toContainText('3 条');
  await expect(page.getByTestId('evidence-groups')).toContainText(command);
  await expect(page.getByTestId('evidence-groups')).toContainText(error);
  await expect(page.getByTestId('evidence-groups')).not.toContainText(`会话 ${conversation}`);
  await expect(page.getByTestId('evidence-groups')).not.toContainText('N 行');
  await page.getByRole('button', { name: '查看会话' }).first().click();
  const drawer = page.getByRole('dialog');
  await expect(drawer).toContainText('当前信号命中');
  await expect(drawer).toContainText(command);
  await expect(drawer).toContainText(error);
});
