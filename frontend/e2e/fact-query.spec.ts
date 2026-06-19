import { expect, test } from '@playwright/test';

test('ingested low evidence facts are visible and filterable in Fact Query', async ({ page, request }) => {
  const suffix = Date.now().toString();
  const factId = `e2e-low-fact-${suffix}`;
  const summary = `E2E low evidence fact remains queryable ${suffix}`;
  const ingest = await request.post('http://127.0.0.1:8765/api/telemetry/ingest', {
    data: {
      batch_id: `e2e-fact-query-${suffix}`,
      collector_id: 'collector-codex',
      source: 'codex',
      cursor: `cursor-e2e-${suffix}`,
      items: [
        {
          source_event_id: factId,
          fact_type: 'unknown',
          category: 'uncategorized',
          quality: 'low',
          severity: 'low',
          summary,
          occurred_at: new Date().toISOString(),
          span: 'session:e2e',
          raw_hash: 'hash-e2e-low-001',
          projection: { classification: 'unknown' },
          source_refs: { conversation_ref: 'conv-e2e-hash' },
          source_specific: { codex_event_type: 'message_summary' }
        }
      ]
    }
  });
  expect(ingest.ok()).toBeTruthy();

  await page.goto('/');
  await page.getByRole('button', { name: /事实查询 证据与原文/ }).click();
  await expect(page.getByText('显示采集器自检与心跳')).toBeVisible();
  await expect(page.getByLabel('事实查询摘要')).toContainText('待补证');
  await expect(page.getByText(summary)).toBeVisible();
  await page.getByLabel('质量').selectOption('low');
  const viewButton = page.getByRole('button', { name: `查看 ${factId}` });
  const row = page.getByRole('row').filter({ has: viewButton });
  await expect(row).toBeVisible();
  await expect(row).toContainText(summary);
  await expect(row).toContainText('待补证');
  await expect(row).toContainText('未上传原文，可查看摘要和字段');
  await viewButton.click();
  await expect(page.getByText('hash-e2e-low-001')).toBeVisible();
  await expect(page.getByText(/未上传原文，本条只能查看摘要、字段和值/)).toBeVisible();

  const query = await request.get('http://127.0.0.1:8765/api/facts?quality=low');
  const body = await query.json();
  expect(body.facts.some((fact: { fact_id: string; quality: string; content_preview?: string }) => (
    fact.fact_id === factId && fact.quality === 'low' && fact.content_preview === summary
  ))).toBeTruthy();
});
