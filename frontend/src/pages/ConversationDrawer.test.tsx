import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import type { ConversationDetail, ConversationHit, ConversationHitsResponse, ConversationMessagesResponse } from '../api/types';
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
  messages_total: 0,
  hits_total: 0,
};

const phoneHit: ConversationHit = {
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
};

const technicalHit: ConversationHit = {
  fact_id: 'fact-tool-1',
  category: 'tool_result',
  fact_type: 'tool',
  severity: 'low',
  occurred_at: '2026-07-01T10:30:00Z',
  summary: 'Claude 工具结果已采集：Bash。',
  content_preview: '',
  tool_context: null,
  sensitive_matches: [],
};

function makeLoaders(overrides: {
  messages?: () => Promise<ConversationMessagesResponse>;
  hits?: () => Promise<ConversationHitsResponse>;
} = {}) {
  return {
    loadMessages: vi.fn(overrides.messages ?? (() => Promise.resolve({
      messages: [], total: 0, page: 1, page_size: 50, has_more: false,
    }))),
    loadHits: vi.fn(overrides.hits ?? (() => Promise.resolve({
      hits: [], total: 0, page: 1, page_size: 50, has_more: false,
    }))),
    locateMessage: vi.fn(() => Promise.resolve({ page: 1, page_size: 50, fact_id: '' })),
    loadHitsByFactIds: vi.fn(() => Promise.resolve({ hits: [] })),
  };
}

describe('ConversationDrawer', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it('含 high confidence 敏感命中的 low severity tool hit 应展开显示', async () => {
    const loaders = makeLoaders({
      hits: () => Promise.resolve({
        hits: [phoneHit], total: 1, page: 1, page_size: 50, has_more: false,
      }),
    });
    render(<ConversationDrawer detail={{ ...baseDetail, hits_total: 1 }} onClose={() => {}} {...loaders} />);
    // 切到 hits tab（默认 messages tab）
    fireEvent.click(screen.getByRole('tab', { name: /命中内容/ }));
    await waitFor(() => {
      expect(screen.getByText(/13812345678/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/已折叠/)).not.toBeInTheDocument();
  });

  it('不含敏感命中的 low severity tool hit 应折叠', async () => {
    const loaders = makeLoaders({
      hits: () => Promise.resolve({
        hits: [technicalHit], total: 1, page: 1, page_size: 50, has_more: false,
      }),
    });
    render(<ConversationDrawer detail={{ ...baseDetail, hits_total: 1 }} onClose={() => {}} {...loaders} />);
    fireEvent.click(screen.getByRole('tab', { name: /命中内容/ }));
    await waitFor(() => {
      expect(screen.getByText(/本页已折叠/)).toBeInTheDocument();
    });
  });

  it('technicalHits 折叠区可展开查看', async () => {
    const loaders = makeLoaders({
      hits: () => Promise.resolve({
        hits: [technicalHit], total: 1, page: 1, page_size: 50, has_more: false,
      }),
    });
    render(<ConversationDrawer detail={{ ...baseDetail, hits_total: 1 }} onClose={() => {}} {...loaders} />);
    fireEvent.click(screen.getByRole('tab', { name: /命中内容/ }));
    await waitFor(() => {
      expect(screen.getByText(/本页已折叠/)).toBeInTheDocument();
    });
    // 点击展开
    fireEvent.click(screen.getByTestId('toggle-technical-hits'));
    expect(screen.getByText('收起')).toBeInTheDocument();
  });

  it('Tab 切换触发按需加载', async () => {
    const loaders = makeLoaders({
      messages: () => Promise.resolve({
        messages: [
          { fact_id: 'm1', role: 'user', category: 'agent_prompt', occurred_at: '2026-07-01T10:00:00Z', content: 'hello', raw_available: false },
        ],
        total: 1, page: 1, page_size: 50, has_more: false,
      }),
      hits: () => Promise.resolve({
        hits: [phoneHit], total: 1, page: 1, page_size: 50, has_more: false,
      }),
    });
    render(<ConversationDrawer detail={{ ...baseDetail, messages_total: 1, hits_total: 1 }} onClose={() => {}} {...loaders} />);
    // 默认 messages tab，应该已加载 messages
    await waitFor(() => {
      expect(loaders.loadMessages).toHaveBeenCalled();
    });
    // 切到 hits tab
    fireEvent.click(screen.getByRole('tab', { name: /命中内容/ }));
    await waitFor(() => {
      expect(loaders.loadHits).toHaveBeenCalled();
    });
  });

  it('刷新按钮重置当前 tab', async () => {
    const loaders = makeLoaders({
      messages: () => Promise.resolve({
        messages: [
          { fact_id: 'm1', role: 'user', category: 'agent_prompt', occurred_at: '2026-07-01T10:00:00Z', content: 'hello', raw_available: false },
        ],
        total: 1, page: 1, page_size: 50, has_more: false,
      }),
    });
    render(<ConversationDrawer detail={{ ...baseDetail, messages_total: 1 }} onClose={() => {}} {...loaders} />);
    await waitFor(() => {
      expect(loaders.loadMessages).toHaveBeenCalledTimes(1);
    });
    fireEvent.click(screen.getByTestId('drawer-refresh'));
    await waitFor(() => {
      expect(loaders.loadMessages).toHaveBeenCalledTimes(2);
    });
  });

  it('ESC 键关闭 drawer', async () => {
    const onClose = vi.fn();
    render(<ConversationDrawer detail={baseDetail} onClose={onClose} {...makeLoaders()} />);
    await act(async () => {
      vi.advanceTimersByTime(0);
    });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('点击 backdrop 关闭 drawer', async () => {
    const onClose = vi.fn();
    const { container } = render(<ConversationDrawer detail={baseDetail} onClose={onClose} {...makeLoaders()} />);
    await act(async () => { vi.advanceTimersByTime(0); });
    const backdrop = container.querySelector('.drawer-backdrop');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalled();
  });
});
