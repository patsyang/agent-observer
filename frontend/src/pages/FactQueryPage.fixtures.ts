import type { FactDetail, FactsResponse } from '../api/types';

export const facts: FactsResponse = {
  total: 2,
  limit: 50,
  offset: 0,
  facts: [
    {
      fact_id: 'event-low-001',
      fact_type: 'unknown',
      category: 'uncategorized',
      quality: 'low',
      severity: 'low',
      summary: 'Low evidence fact remains queryable',
      occurred_at: '2026-06-18T10:01:00+00:00',
      ingested_at: '2026-06-18T10:02:00+00:00',
      source: 'codex',
      promoted_to_story: false,
      source_event_type: 'message',
      source_label: 'Codex 会话 conv-hash-001',
      content_preview: 'Prompt: 请检查 Dashboard 为什么没有数据',
      raw_available: true,
      raw_status: '已上传原文'
    },
    {
      fact_id: 'event-error-001',
      fact_type: 'error',
      category: 'tool_failure',
      quality: 'high',
      severity: 'high',
      summary: 'Tool execution failed with raw signature',
      occurred_at: '2026-06-18T10:00:00+00:00',
      ingested_at: '2026-06-18T10:02:00+00:00',
      source: 'codex',
      promoted_to_story: false,
      source_event_type: 'tool_result',
      source_label: 'Codex 会话 conv-hash-001',
      content_preview: '工具 shell_command，退出码 1',
      raw_available: false,
      raw_status: '仅结构化字段'
    }
  ]
};

export const detail: FactDetail = {
  fact: facts.facts[0],
  evidence_projection: {
    projection_id: 'proj-event-low-001',
    fact_id: 'event-low-001',
    category: 'uncategorized',
    span: 'session:demo',
    raw_hash: 'hash-low-001',
    projection_json: { role: 'user', content_length: 18, prompt_text: '请检查 Dashboard 为什么没有数据' },
    upload_raw: true,
    raw_content: '{"payload":{"content":[{"text":"请检查 Dashboard 为什么没有数据"}]}}'
  },
  evidence_projections: [
    {
      projection_id: 'proj-event-low-001',
      fact_id: 'event-low-001',
      category: 'codex_prompt',
      span: 'session:demo',
      raw_hash: 'hash-low-001',
      projection_json: { role: 'user', content_length: 18, prompt_text: '请检查 Dashboard 为什么没有数据' },
      upload_raw: true,
      raw_content: '{"payload":{"content":[{"text":"请检查 Dashboard 为什么没有数据"}]}}'
    }
  ],
  source_refs: { conversation_ref: 'conv-hash-001' },
  source_specific_json: { codex_event_type: 'message' }
};
