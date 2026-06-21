import { expect, test } from '@playwright/test';
import { E2E_API_BASE } from './support/urls';

test('operator opens Dashboard story queue and drills into evidence chain', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const summary = `E2E checkout workflow failed repeatedly ${suffix}`;
  const signature = `sig-e2e-checkout-${suffix}`;
  const conversation = `conversation-e2e-story-${suffix}`;
  const errorFact = `e2e-story-error-${suffix}`;
  const usageFact = `e2e-story-usage-${suffix}`;
  const ingest = await request.post(`${E2E_API_BASE}/api/telemetry/ingest`, {
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
  const rebuilt = await request.post(`${E2E_API_BASE}/api/stories/rebuild`, { data: { reason: 'e2e' } });
  expect(rebuilt.ok()).toBeTruthy();
  const storyKey = `error:${signature}`;

  await page.goto('/');
  const storyCard = page.locator(`[data-story-key="${storyKey}"]`);
  await expect(storyCard).toBeVisible({ timeout: 15000 });
  await expect(storyCard).not.toContainText(summary);
  await storyCard.getByTestId('open-story').click();
  await expect(page.getByTestId('story-detail')).toBeVisible();
  const evidenceChain = page.getByTestId('evidence-chain');
  await expect(page.getByTestId('evidence-chain-table')).toBeVisible();
  await expect(evidenceChain).toContainText(summary);
  await expect(evidenceChain).not.toContainText('用量 64 token，活动 缺陷修复');
  await expect(evidenceChain.getByTestId('open-fact-conversation')).toBeVisible();
  await expect(evidenceChain.getByRole('cell').first()).not.toContainText(`proj-${errorFact}`);

  const stories = await request.get(`${E2E_API_BASE}/api/stories`);
  const body = await stories.json();
  const story = body.stories.find((item: { story_key: string }) => item.story_key === storyKey);
  expect(story.evidence_refs).toEqual([]);
  const detail = await request.get(`${E2E_API_BASE}/api/stories/${story.story_id}`);
  const detailBody = await detail.json();
  expect(detailBody.evidence_refs).toContain(`proj-${errorFact}`);
  expect(detailBody.current_snapshot.evidence_chain.some((entry: { summary: string }) => entry.summary === summary)).toBeTruthy();
});
