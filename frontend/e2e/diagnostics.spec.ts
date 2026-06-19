import { expect, test } from '@playwright/test';

test('operator requests diagnostic and sees result in evidence chain', async ({ page, request }) => {
  const batchId = `e2e-diagnostic-${Date.now()}`;
  const summary = `E2E diagnostic command failed ${batchId}`;
  await request.post('http://127.0.0.1:8765/api/collectors/register', {
    data: {
      collector_id: 'collector-e2e-diagnostic',
      display_name: 'E2E diagnostic collector',
      hostname: 'e2e-diagnostic-host',
      windows_username: 'e2e-diagnostic-user'
    }
  });
  await request.post('http://127.0.0.1:8765/api/collectors/collector-e2e-diagnostic/heartbeat', {
    data: { source_status: 'online', reason_code: 'ok' }
  });
  await request.post('http://127.0.0.1:8765/api/telemetry/ingest', {
    data: {
      batch_id: batchId,
      collector_id: 'collector-e2e-diagnostic',
      source: 'codex',
      cursor: `cursor-${batchId}`,
      items: [
        {
          source_event_id: `${batchId}-error`,
          fact_type: 'error',
          category: 'codex_error',
          quality: 'high',
          severity: 'high',
          summary,
          occurred_at: new Date().toISOString(),
          span: 'conversation:e2e-diagnostic',
          raw_hash: `hash-${batchId}`,
          projection: { signature_key: `sig-${batchId}` },
          error_signature: { signature_key: `sig-${batchId}`, category: 'codex_error' },
          source_refs: { conversation_ref: 'conversation-e2e-diagnostic' }
        }
      ]
    }
  });
  const rebuilt = await request.post('http://127.0.0.1:8765/api/stories/rebuild', { data: { reason: 'e2e-diagnostic' } });
  const story = (await rebuilt.json()).stories.find((item: { story_key: string }) => item.story_key === `error:sig-${batchId}`);

  await page.goto('/');
  const storyCard = page.locator(`[data-story-key="${story.story_key}"]`);
  await expect(storyCard).toContainText('发现 1 次 Codex 工具执行失败');
  await expect(storyCard).not.toContainText(summary);
  await storyCard.getByRole('button').click();
  await expect(page.getByLabel('诊断操作')).toContainText('Codex 错误上下文');
  await page.getByRole('button', { name: '补充上下文' }).click();
  await expect(page.getByLabel('诊断操作')).toContainText('诊断 排队中');

  const detailAfterRequest = await request.get(`http://127.0.0.1:8765/api/stories/${story.story_id}`);
  expect((await detailAfterRequest.json()).diagnostic_status_summary.status).toBe('pending');
  const jobs = await request.get(`http://127.0.0.1:8765/api/stories/${story.story_id}/diagnostics/availability`);
  const jobId = (await jobs.json()).active_job.job_id;
  await request.post(`http://127.0.0.1:8765/api/diagnostics/${jobId}/result`, {
    data: { status: 'succeeded', summary: 'Config category collected' }
  });

  await page.goto('/');
  await page.locator(`[data-story-key="${story.story_key}"]`).getByRole('button').click();
  await expect(page.getByLabel('证据链')).toContainText('补证结果');
  await expect(page.getByLabel('故事详情')).toContainText('诊断成功');
});
