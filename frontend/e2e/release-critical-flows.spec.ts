import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test, type APIRequestContext } from '@playwright/test';

interface E2EFact {
  category: string;
}

interface E2EStory {
  story_id: string;
  story_key: string;
}

function codexRecords() {
  const now = new Date().toISOString();
  const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
  return [
    {
      timestamp: sevenDaysAgo,
      type: 'message',
      content: 'documented 7 day local sample baseline marker',
      conversation_id: 'conversation-e2e-history',
      session_id: 'session-e2e-history',
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
      type: 'message',
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
      type: 'message',
      sensitive_categories: ['credential'],
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
  const zipPath = join(outputDir, 'agent-observer-windows.zip');
  const packageResponse = await request.get('http://127.0.0.1:8765/api/client-package/windows');
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

  const factsResponse = await request.get('http://127.0.0.1:8765/api/facts');
  const facts = (await factsResponse.json()) as { facts: E2EFact[] };
  expect(facts.facts.some((fact) => fact.category === 'codex_error')).toBeTruthy();
  expect(facts.facts.some((fact) => fact.category === 'usage')).toBeTruthy();
  expect(facts.facts.some((fact) => fact.category === 'high_risk_operation')).toBeTruthy();
  expect(facts.facts.some((fact) => fact.category === 'sensitive_touch')).toBeTruthy();

  await page.goto('/');
  await expect(page.getByLabel('观察故事运营台')).toContainText('观察故事队列');
  await expect(page.getByText(/错误指纹/).first()).toBeVisible();
  await expect(page.getByLabel('证据、用量和风险')).toContainText('归因用量');
  await page.getByRole('button', { name: /事实查询 证据与原文/ }).click();
  await expect(page.getByRole('heading', { level: 1, name: '事实查询' })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'Codex 错误' }).first()).toBeVisible();
  await page.getByRole('button', { name: /采集器 状态与策略/ }).click();
  await expect(page.getByRole('heading', { level: 1, name: '采集器' })).toBeVisible();
  await expect(page.getByText(collectorId).first()).toBeVisible();

  const storiesResponse = await request.get('http://127.0.0.1:8765/api/stories?include_hidden=true');
  const stories = (await storiesResponse.json()) as { stories: E2EStory[] };
  const errorStory = stories.stories.find((story) => story.story_key.startsWith('error:'));
  expect(errorStory).toBeTruthy();
  const storyId = errorStory!.story_id;
  const handle = await request.post(`http://127.0.0.1:8765/api/stories/${storyId}/handle`, {
    data: { conclusion_code: 'known_issue', note: '已确认需要跟进' }
  });
  expect(handle.ok()).toBeTruthy();
  const diagnostic = await request.post(`http://127.0.0.1:8765/api/stories/${storyId}/diagnostics`, {
    data: { capability_id: 'codex_error_context' }
  });
  expect(diagnostic.ok()).toBeTruthy();
  execFileSync('cmd.exe', ['/d', '/s', '/c', 'agent-observer.cmd run-once'], { cwd: outputDir, encoding: 'utf-8' });

  const policy = await (await request.get('http://127.0.0.1:8765/api/policy')).json();
  const policyUpdate = await request.patch('http://127.0.0.1:8765/api/policy', {
    data: {
      expected_version: policy.policy_version,
      template_enabled: true,
      upload_raw: false,
      collection_policy: 'codex default local observation',
      diagnostic_policy: 'whitelist only'
    }
  });
  expect(policyUpdate.ok()).toBeTruthy();

  const validation = await request.post('http://127.0.0.1:8765/api/validation/minimum-experiment');
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
