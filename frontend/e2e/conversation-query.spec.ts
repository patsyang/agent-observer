import { expect, test } from '@playwright/test';
import { E2E_API_BASE } from './support/urls';

test('operator queries conversations by prompt and response keywords', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const conversation = `conv-e2e-query-${suffix}`;
  const prompt = `E2E 提交 Prompt ${suffix}`;
  const response = `E2E 响应内容 ${suffix}`;
  const now = new Date().toISOString();
  const ingest = await request.post(`${E2E_API_BASE}/api/telemetry/ingest`, {
    data: {
      batch_id: `e2e-conversation-query-${suffix}`,
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      collector_id: 'collector-codex',
      source: 'codex',
      cursor: `cursor-e2e-${suffix}`,
      items: [
        {
          source_event_id: `e2e-prompt-${suffix}`,
          fact_type: 'content',
          category: 'codex_prompt',
          quality: 'high',
          severity: 'low',
          summary: prompt,
          occurred_at: now,
          span: `session:${conversation}`,
          raw_hash: `hash-prompt-${suffix}`,
          projection: { role: 'user', prompt_text: prompt },
          upload_raw: true,
          raw_content: prompt,
          source_refs: { conversation_ref: conversation, session_ref: `session-${conversation}` },
          source_specific: { codex_event_type: 'message' }
        },
        {
          source_event_id: `e2e-response-${suffix}`,
          fact_type: 'content',
          category: 'codex_message',
          quality: 'high',
          severity: 'low',
          summary: response,
          occurred_at: now,
          span: `session:${conversation}`,
          raw_hash: `hash-response-${suffix}`,
          projection: { role: 'assistant', content_text: response },
          upload_raw: true,
          raw_content: response,
          source_refs: { conversation_ref: conversation, session_ref: `session-${conversation}` },
          source_specific: { codex_event_type: 'message' }
        },
        {
          source_event_id: `e2e-usage-${suffix}`,
          fact_type: 'usage',
          category: 'usage',
          quality: 'high',
          severity: 'low',
          summary: 'E2E conversation usage',
          occurred_at: now,
          span: `usage:${conversation}`,
          raw_hash: `hash-usage-${suffix}`,
          projection: { activity_tag: 'codex_turn', units: 88 },
          usage: { units: 88, activity_tag: 'codex_turn', conversation_id: conversation },
          source_refs: { conversation_ref: conversation },
          source_specific: { codex_event_type: 'usage_summary' }
        }
      ]
    }
  });
  expect(ingest.ok()).toBeTruthy();

  await page.goto('/');
  await page.getByTestId('nav-conversations').click();
  await expect(page.getByTestId('conversation-page')).toBeVisible();
  await page.getByTestId('prompt-query').fill(suffix);
  await page.getByTestId('response-query').fill('E2E 响应');
  await page.getByTestId('conversation-search').click();
  const row = page.locator(`[data-conversation-ref="${conversation}"]`);
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(row).toContainText(response);
  await row.click();
  const drawer = page.getByTestId('conversation-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText(prompt);
  await expect(drawer).toContainText(response);
  await expect(drawer).toContainText('88');

  const query = await request.get(`${E2E_API_BASE}/api/conversations?window=all&prompt_query=${suffix}`);
  const body = await query.json();
  expect(body.conversations.some((item: { conversation_ref: string; prompt_preview: string }) => (
    item.conversation_ref === conversation && item.prompt_preview === prompt
  ))).toBeTruthy();
});
