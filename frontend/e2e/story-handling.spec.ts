import { expect, test } from '@playwright/test';

test('operator handles a story and recurrence returns it with conclusion preserved', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const signatureKey = `sig-e2e-handling-${suffix}`;
  const summary = `E2E checkout handling workflow failed ${suffix}`;
  const storyKey = `error:${signatureKey}`;
  const occurredAt = new Date().toISOString();
  const firstBatch = {
    batch_id: `e2e-handling-${suffix}-001`,
    collector_id: 'collector-codex',
    source: 'codex',
    cursor: `cursor-e2e-handling-${suffix}-001`,
    items: [
      {
        source_event_id: `e2e-handling-error-${suffix}-001`,
        fact_type: 'error',
        category: 'codex_error',
        quality: 'high',
        severity: 'high',
        summary,
        occurred_at: occurredAt,
        span: 'command:checkout',
        raw_hash: `hash-e2e-handling-error-${suffix}-001`,
        projection: { impact: 'checkout workflow', count: 1 },
        error_signature: { signature_key: signatureKey, category: 'codex_error' },
        source_refs: { conversation_ref: `conversation-e2e-handling-${suffix}` },
        source_specific: { codex_event_type: 'tool_result' }
      }
    ]
  };
  await expect((await request.post('http://127.0.0.1:8765/api/telemetry/ingest', { data: firstBatch })).ok()).toBeTruthy();
  const rebuilt = await request.post('http://127.0.0.1:8765/api/stories/rebuild', { data: { reason: 'handling-e2e' } });
  const storyId = (await rebuilt.json()).stories.find(
    (story: { story_key: string }) => story.story_key === storyKey
  ).story_id;

  await page.goto('/');
  const storyCard = page.locator(`[data-story-key="${storyKey}"]`);
  await expect(storyCard).toContainText('发现 1 次 Codex 工具执行失败');
  await expect(storyCard).not.toContainText(summary);
  await storyCard.getByRole('button').click();
  await page.getByRole('button', { name: /处理故事/ }).click();
  await page.getByRole('button', { name: /^处理$/ }).click();
  await expect(page.getByRole('alert')).toContainText('必须选择结构化结论');
  await page.getByLabel(/结论/).selectOption('known_issue');
  await page.getByLabel(/备注/).fill('Tracked in backlog');
  await page.getByRole('button', { name: /^处理$/ }).click();
  await expect(page.getByLabel('故事详情')).toContainText('已处理隐藏，已处理，已知问题');
  await expect(page.getByLabel('故事详情')).toContainText('story_handling_changed by fixed-management-account');

  const handled = await request.get(`http://127.0.0.1:8765/api/stories/${storyId}`);
  expect((await handled.json()).conclusion_code).toBe('known_issue');
  const defaultQueue = await request.get('http://127.0.0.1:8765/api/stories');
  expect((await defaultQueue.json()).stories.some((story: { story_id: string }) => story.story_id === storyId)).toBeFalsy();

  await request.post('http://127.0.0.1:8765/api/telemetry/ingest', {
    data: {
      ...firstBatch,
      batch_id: `e2e-handling-${suffix}-002`,
      cursor: `cursor-e2e-handling-${suffix}-002`,
      items: [
        {
          ...firstBatch.items[0],
          source_event_id: `e2e-handling-error-${suffix}-002`,
          summary: `${summary} with new evidence`,
          raw_hash: `hash-e2e-handling-error-${suffix}-002`
        }
      ]
    }
  });
  await request.post('http://127.0.0.1:8765/api/stories/rebuild', { data: { reason: 'handling-recurrence' } });
  await page.goto('/');
  await expect(page.locator(`[data-story-key="${storyKey}"]`)).toContainText('需复核');
  const recurrent = await request.get(`http://127.0.0.1:8765/api/stories/${storyId}`);
  const recurrentBody = await recurrent.json();
  expect(recurrentBody.attention_state).toBe('needs_review');
  expect(recurrentBody.conclusion_code).toBe('known_issue');
});
