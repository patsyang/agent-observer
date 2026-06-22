import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type APIRequestContext } from '@playwright/test';
import { enableEnrichment } from './support/api';
import { E2E_API_BASE } from './support/urls';

interface E2ESignal {
  signal_id: string;
  signal_kind: string;
}

function codexRecords() {
  const now = new Date().toISOString();
  const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
  return [
    {
      timestamp: sevenDaysAgo,
      type: 'unclassified_local_event',
      observed_keys: ['documented_7_day_local_sample'],
      conversation_id: 'conversation-e2e-history',
      session_id: 'session-e2e-history',
      project: 'agent-observer',
      validation_sample: 'documented_7_day_local_sample'
    },
    {
      timestamp: now,
      type: 'user_message',
      role: 'user',
      content: '请运行 release critical packaged collector flow',
      conversation_id: 'conversation-e2e',
      session_id: 'session-e2e',
      project: 'agent-observer',
      validation_sample: 'documented_7_day_local_sample'
    },
    {
      timestamp: now,
      type: 'agent_message',
      role: 'assistant',
      content: '已运行 packaged collector，并发现工具执行失败。',
      conversation_id: 'conversation-e2e',
      session_id: 'session-e2e',
      project: 'agent-observer',
      validation_sample: 'documented_7_day_local_sample'
    },
    {
      timestamp: now,
      type: 'tool_result',
      tool: 'shell',
      exit_code: 1,
      phase: 'test',
      conversation_id: 'conversation-e2e',
      session_id: 'session-e2e',
      project: 'agent-observer',
      validation_sample: 'documented_7_day_local_sample'
    },
    {
      timestamp: now,
      type: 'usage',
      total_tokens: 140,
      activity_tags: ['test_run', 'shell_debug'],
      conversation_id: 'conversation-e2e',
      session_id: 'session-e2e',
      project: 'agent-observer',
      validation_sample: 'documented_7_day_local_sample'
    },
    {
      timestamp: now,
      type: 'tool_call',
      tool: 'apply_patch',
      operation: 'delete',
      path: 'backend/app/config.py',
      conversation_id: 'conversation-e2e',
      session_id: 'session-e2e',
      project: 'agent-observer',
      validation_sample: 'documented_7_day_local_sample'
    },
    {
      timestamp: now,
      type: 'response_item',
      payload: {
        type: 'function_call',
        name: 'shell_command',
        arguments: JSON.stringify({
          command: 'curl -H "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456" http://127.0.0.1'
        })
      },
      conversation_id: 'conversation-e2e',
      session_id: 'session-e2e',
      project: 'agent-observer',
      validation_sample: 'documented_7_day_local_sample'
    }
  ];
}

async function downloadAndRunCollector(request: APIRequestContext, outputDir: string) {
  rmSync(outputDir, { recursive: true, force: true });
  mkdirSync(outputDir, { recursive: true });
  await enableEnrichment(request);
  const zipPath = join(outputDir, 'agent-observer-windows.zip');
  const packageResponse = await request.get(`${E2E_API_BASE}/api/client-package/windows`);
  expect(packageResponse.ok()).toBeTruthy();
  writeFileSync(zipPath, await packageResponse.body());
  execFileSync('powershell', ['-NoProfile', '-Command', `Expand-Archive -Force -LiteralPath '${zipPath}' -DestinationPath '${outputDir}'`]);

  const codexHome = join(outputDir, '.codex');
  mkdirSync(join(codexHome, 'sessions'), { recursive: true });
  writeFileSync(join(codexHome, 'sessions', 'session-e2e.jsonl'), codexRecords().map((record) => JSON.stringify(record)).join('\n'));

  const configPath = join(outputDir, 'agent-observer.config.json');
  const config = JSON.parse(readFileSync(configPath, 'utf-8'));
  config.collector_id = `collector-e2e-${Date.now()}`;
  config.codex_home = codexHome;
  config.collection_interval_seconds = 0;
  writeFileSync(configPath, JSON.stringify(config, null, 2));

  const first = execFileSync('cmd.exe', ['/d', '/s', '/c', 'agent-observer.cmd run-once'], { cwd: outputDir, encoding: 'utf-8' });
  expect(JSON.parse(first.trim()).uploaded).toBeGreaterThan(1);
  return { collectorId: config.collector_id, outputDir };
}

test('release critical flows use packaged collector telemetry and DB-backed validation', async ({ page, request }, testInfo) => {
  const { collectorId, outputDir } = await downloadAndRunCollector(request, testInfo.outputPath('collector-package'));

  const conversationsResponse = await request.get(`${E2E_API_BASE}/api/conversations?window=all`);
  const conversations = await conversationsResponse.json();
  expect(conversations.conversations.some((item: { hit_count: number; token_usage: { effective_units: number } }) => (
    item.hit_count >= 3 && item.token_usage.effective_units === 140
  ))).toBeTruthy();
  const usageResponse = await request.get(`${E2E_API_BASE}/api/usage/summary`);
  expect((await usageResponse.json()).totals.effective_units).toBeGreaterThan(0);
  const riskResponse = await request.get(`${E2E_API_BASE}/api/risks/summary`);
  expect((await riskResponse.json()).signals.length).toBeGreaterThan(0);

  await page.goto('/');
  await expect(page.getByTestId('dashboard-page')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('signal-queue')).toBeVisible();
  await expect(page.getByTestId('usage-governance')).toBeVisible();
  await page.getByTestId('nav-conversations').click();
  await expect(page.getByTestId('conversation-page')).toBeVisible();
  await page.getByTestId('nav-collectors').click();
  await expect(page.getByTestId('collectors-page')).toBeVisible();
  await expect(page.getByText(collectorId).first()).toBeVisible();

  const signalsResponse = await request.get(`${E2E_API_BASE}/api/signals?window=all`);
  const signals = (await signalsResponse.json()) as { signals: E2ESignal[] };
  const failureSignal = signals.signals.find((signal) => signal.signal_kind === 'tool_execution_failure');
  expect(failureSignal).toBeTruthy();
  const signalId = failureSignal!.signal_id;
  const handle = await request.post(`${E2E_API_BASE}/api/signals/${signalId}/handle`, {
    data: { conclusion_code: 'known_issue', note: '已确认需要跟进' }
  });
  expect(handle.ok()).toBeTruthy();
  const enrichment = await request.post(`${E2E_API_BASE}/api/signals/${signalId}/enrichments`, {
    data: { capability_id: 'codex_tool_failure_context' }
  });
  expect(enrichment.ok()).toBeTruthy();
  execFileSync('cmd.exe', ['/d', '/s', '/c', 'agent-observer.cmd run-once'], { cwd: outputDir, encoding: 'utf-8' });

  const currentPolicy = await (await request.get(`${E2E_API_BASE}/api/policy`)).json();
  const disabled = await request.patch(`${E2E_API_BASE}/api/policy`, {
    data: { expected_version: currentPolicy.policy_version, enrichment_mode: 'disabled' }
  });
  expect(disabled.ok()).toBeTruthy();
  const disabledPolicy = await disabled.json();
  const enabled = await request.patch(`${E2E_API_BASE}/api/policy`, {
    data: { expected_version: disabledPolicy.policy_version, enrichment_mode: 'enabled' }
  });
  expect(enabled.ok()).toBeTruthy();

  const validation = await request.post(`${E2E_API_BASE}/api/validation/minimum-experiment`);
  expect(validation.ok()).toBeTruthy();
  const report = await validation.json();
  expect(report.result).toBe('PASS');
  expect(report.stop_marker).toBe(false);
  expect(report.sample_source).toBe('documented_7_day_local_data_sample');
  const flowCoverage = Object.values(report.flow_coverage) as Array<{ covered: boolean }>;
  const acceptanceCoverage = Object.values(report.acceptance_coverage) as Array<{ covered: boolean }>;
  expect(flowCoverage.every((row) => row.covered)).toBe(true);
  expect(acceptanceCoverage.every((row) => row.covered)).toBe(true);
});
