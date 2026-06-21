import { expect, test } from '@playwright/test';
import { enableEnrichment } from './support/api';
import { E2E_API_BASE } from './support/urls';

test('operator requests enrichment and sees result in evidence chain', async ({ page, request }) => {
  const batchId = `e2e-enrichment-${Date.now()}`;
  const summary = `E2E enrichment command failed ${batchId}`;
  await enableEnrichment(request);
  await request.post(`${E2E_API_BASE}/api/collectors/register`, {
    data: {
      collector_id: 'collector-e2e-enrichment',
      display_name: 'E2E enrichment collector',
      hostname: 'e2e-enrichment-host',
      windows_username: 'e2e-enrichment-user',
      agent_type: 'codex',
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0'
    }
  });
  await request.post(`${E2E_API_BASE}/api/collectors/collector-e2e-enrichment/heartbeat`, {
    data: {
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      source_status: 'online',
      reason_code: 'ok'
    }
  });
  await request.post(`${E2E_API_BASE}/api/telemetry/ingest`, {
    data: {
      batch_id: batchId,
      protocol_version: 'agent-observer-telemetry/v2',
      agent_version: '0.2.0',
      collector_id: 'collector-e2e-enrichment',
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
          span: 'conversation:e2e-enrichment',
          raw_hash: `hash-${batchId}`,
          projection: { signature_key: `sig-${batchId}` },
          error_signature: { signature_key: `sig-${batchId}`, category: 'codex_error' },
          source_refs: { conversation_ref: 'conversation-e2e-enrichment' }
        }
      ]
    }
  });
  const rebuilt = await request.post(`${E2E_API_BASE}/api/stories/rebuild`, { data: { reason: 'e2e-enrichment' } });
  const story = (await rebuilt.json()).stories.find((item: { story_key: string }) => item.story_key === `error:sig-${batchId}`);

  await page.goto('/');
  const storyCard = page.locator(`[data-story-key="${story.story_key}"]`);
  await expect(storyCard).toBeVisible({ timeout: 15000 });
  await expect(storyCard).not.toContainText(summary);
  await storyCard.getByTestId('open-story').click();
  await expect(page.getByTestId('enrichment-panel')).toBeVisible();
  await page.getByTestId('request-enrichment').click();
  await expect(page.getByTestId('enrichment-panel').getByRole('status')).toBeVisible();

  const detailAfterRequest = await request.get(`${E2E_API_BASE}/api/stories/${story.story_id}`);
  expect((await detailAfterRequest.json()).enrichment_status_summary.status).toBe('pending');
  const nextJobResponse = await request.get(`${E2E_API_BASE}/api/collectors/collector-e2e-enrichment/enrichments/next`);
  const nextJob = await nextJobResponse.json();
  expect(nextJob.capability_id).toBe('codex_tool_failure_context');
  expect(nextJob.command).toMatchObject({
    command_id: 'collect_codex_tool_failure_context',
    story_id: story.story_id,
    capability_id: 'codex_tool_failure_context'
  });
  expect(nextJob.command.evidence_refs.length).toBeGreaterThan(0);
  await request.post(`${E2E_API_BASE}/api/collectors/collector-e2e-enrichment/enrichments/${nextJob.job_id}/result`, {
    data: {
      status: 'succeeded',
      summary: '已补充 1 条工具失败上下文，关联 1 个会话。',
      projection: {
        capability_id: 'codex_tool_failure_context',
        output_schema: 'tool_failure_context.v1',
        matched_conversations: [
          {
            conversation_ref: 'conversation-e2e-enrichment',
            prompt_excerpt: 'run failing command',
            response_excerpt: 'tool failed with exit code 1',
            token_usage: { effective_units: 42 },
            matched_failure_count: 1
          }
        ],
        matched_failures: [
          {
            tool_name: 'shell_command',
            call_id: 'call-e2e-enrichment',
            exit_code: 1,
            command_excerpt: 'npm test -- --bad-flag',
            output_excerpt: 'Exit code: 1',
            occurred_at: new Date().toISOString(),
            source_event_ref: { source_key: 'e2e', line: 1, source_path_hash: 'e2e' },
            conversation_ref: 'conversation-e2e-enrichment',
            token_usage: { effective_units: 42 }
          }
        ],
        redaction: { raw_content_uploaded: false, prompt_uploaded: false, response_uploaded: false }
      },
      redaction: { raw_content_uploaded: false, prompt_uploaded: false, response_uploaded: false }
    }
  });

  await page.goto('/');
  await page.locator(`[data-story-key="${story.story_key}"]`).getByTestId('open-story').click();
  await expect(page.getByTestId('evidence-chain-table')).toBeVisible();
  await expect(page.getByLabel('证据链')).toContainText('命中 1 条失败工具调用');
  const detail = await request.get(`${E2E_API_BASE}/api/stories/${story.story_id}`);
  expect((await detail.json()).enrichment_status_summary.status).toBe('succeeded');
});
