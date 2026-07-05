import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ConversationDetail } from '../api/types';
import { ConversationDrawer } from './ConversationDrawer';

const baseDetail: ConversationDetail = {
  conversation_ref: 'ref:test',
  session_ref: '',
  session_title: '',
  agent_type: 'claude',
  source_id: '',
  source_kind: '',
  started_at: '2026-07-01T10:00:00Z',
  last_event_at: '2026-07-01T11:00:00Z',
  prompt_preview: '',
  response_preview: '',
  event_count: 0,
  hit_count: 0,
  workspace: {
    workspace_id: '',
    workspace_label: 'test-ws',
    workspace_path: '/tmp/test',
    workspace_alias_source: '',
    workspace_confidence: '',
  },
  token_usage: {
    input_token_units: 0,
    output_token_units: 0,
    effective_units: 0,
    cached_input_units: 0,
    cache_observed_input_units: 0,
    cache_hit_rate: 0,
    model_call_count: 0,
    max_single_call_units: 0,
    credit_total: 0,
  },
  messages: [],
  hits: [],
};

describe('ConversationDrawer', () => {
  it('含 high confidence 敏感命中的 low severity tool hit 应展开显示', () => {
    const detail: ConversationDetail = {
      ...baseDetail,
      hits: [
        {
          fact_id: 'fact-phone-1',
          category: 'tool_result',
          fact_type: 'tool',
          severity: 'low',
          occurred_at: '2026-07-01T10:30:00Z',
          summary: 'Claude 工具结果已采集：Bash。',
          content_preview: '',
          tool_context: null,
          sensitive_matches: [
            {
              category: 'phone',
              confidence: 'high',
              match_type: 'phone_number',
              matched_value: '13812345678',
              matched_preview: '13812345678',
              reason_code: 'phone_number',
              evidence_key: 'backfill',
            },
          ],
        },
      ],
    };
    render(<ConversationDrawer detail={detail} onClose={() => {}} />);
    expect(screen.getByText(/13812345678/)).toBeInTheDocument();
    expect(screen.queryByText(/已折叠/)).not.toBeInTheDocument();
  });

  it('不含敏感命中的 low severity tool hit 应折叠', () => {
    const detail: ConversationDetail = {
      ...baseDetail,
      hits: [
        {
          fact_id: 'fact-tool-1',
          category: 'tool_result',
          fact_type: 'tool',
          severity: 'low',
          occurred_at: '2026-07-01T10:30:00Z',
          summary: 'Claude 工具结果已采集：Bash。',
          content_preview: '',
          tool_context: null,
          sensitive_matches: [],
        },
      ],
    };
    render(<ConversationDrawer detail={detail} onClose={() => {}} />);
    expect(screen.getByText(/已折叠/)).toBeInTheDocument();
  });
});
