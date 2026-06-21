import { expect, test } from '@playwright/test';

test('operator opens Dashboard story queue and drills into evidence chain', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const summary = `E2E checkout workflow failed repeatedly ${suffix}`;
  const signature = `sig-e2e-checkout-${suffix}`;
  const conversation = `conversation-e2e-story-${suffix}`;
  const errorFact = `e2e-story-error-${suffix}`;
  const usageFact = `e2e-story-usage-${suffix}`;
  const ingest = await request.post('http://127.0.0.1:8765/api/telemetry/ingest', {
    data: {
      batch_id: `e2e-story-${suffix}`,
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      collector_id: 'collector-codex',
      source: 'codex',
      cursor: `cursor-story-${suffix}`,
      items: [
        {
          source_event_id: errorFact,
          fact_type: 'error',
          category: 'codex_error',
          quality: 'high',
          severity: 'high',
          summary,
          occurred_at: new Date().toISOString(),
          span: 'command:checkout',
          raw_hash: 'hash-e2e-story-error',
          projection: { impact: 'checkout workflow', count: 2 },
          error_signature: { signature_key: signature, category: 'codex_error' },
          source_refs: { conversation_ref: conversation },
          source_specific: { codex_event_type: 'tool_result' }
        },
        {
          source_event_id: usageFact,
          fact_type: 'usage',
          category: 'usage',
          quality: 'high',
          severity: 'low',
          summary: 'E2E story usage',
          occurred_at: new Date().toISOString(),
          span: 'conversation:e2e-story',
          raw_hash: 'hash-e2e-story-usage',
          projection: { activity_tag: 'bug_fix', units: 64 },
          usage: {
            units: 64,
            activity_tag: 'bug_fix',
            conversation_id: conversation
          },
          source_refs: { conversation_ref: conversation },
          source_specific: { codex_event_type: 'usage_summary' }
        }
      ]
    }
  });
  expect(ingest.ok()).toBeTruthy();
  const rebuilt = await request.post('http://127.0.0.1:8765/api/stories/rebuild', { data: { reason: 'e2e' } });
  expect(rebuilt.ok()).toBeTruthy();
  const storyKey = `error:${signature}`;

  await page.goto('/');
  const storyCard = page.locator(`[data-story-key="${storyKey}"]`);
  await expect(storyCard).toContainText('发现 1 条 Codex 工具执行失败命中');
  await expect(storyCard).toContainText('没有用量证据');
  await expect(storyCard).not.toContainText(summary);
  await storyCard.getByRole('button').click();
  await expect(page.getByLabel('信号详情')).toContainText('信号类型：错误复发');
  const evidenceChain = page.getByLabel('证据链');
  await expect(evidenceChain.getByRole('table')).toBeVisible();
  await expect(evidenceChain).toContainText('命中内容');
  await expect(evidenceChain).toContainText('类型 / 来源');
  await expect(evidenceChain).toContainText('可信度 / 原文');
  await expect(evidenceChain).toContainText('操作');
  await expect(evidenceChain).toContainText('Codex 错误');
  await expect(evidenceChain).toContainText(summary);
  await expect(evidenceChain).not.toContainText('用量 64 token，活动 缺陷修复');
  await expect(evidenceChain).toContainText('未上传原文，可查看摘要和字段');
  await expect(evidenceChain).toContainText('查看会话');
  await expect(evidenceChain.getByRole('cell').first()).not.toContainText(`proj-${errorFact}`);

  const stories = await request.get('http://127.0.0.1:8765/api/stories');
  const body = await stories.json();
  const story = body.stories.find((item: { story_key: string }) => item.story_key === storyKey);
  expect(story.evidence_refs).toEqual([]);
  const detail = await request.get(`http://127.0.0.1:8765/api/stories/${story.story_id}`);
  const detailBody = await detail.json();
  expect(detailBody.evidence_refs).toContain(`proj-${errorFact}`);
});
