import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ConversationDetail, ConversationsResponse } from '../api/types';
import { ConversationQueryPage } from './ConversationQueryPage';

const detail: ConversationDetail = {
  conversation_ref: 'conv-alpha',
  session_ref: 'session-alpha',
  started_at: '2026-06-21T01:00:00+00:00',
  last_event_at: '2026-06-21T01:04:00+00:00',
  prompt_preview: '请检查观测总览',
  response_preview: '已经定位信号聚合过宽',
  event_count: 3,
  hit_count: 1,
  token_usage: {
    effective_units: 320,
    cached_input_units: 480,
    input_token_units: 800,
    cache_hit_rate: 0.6,
  },
  messages: [
    {
      fact_id: 'prompt-alpha',
      role: 'user',
      category: 'codex_prompt',
      occurred_at: '2026-06-21T01:00:00+00:00',
      content: '请检查观测总览',
      raw_available: true,
    },
    {
      fact_id: 'response-alpha',
      role: 'assistant',
      category: 'codex_message',
      occurred_at: '2026-06-21T01:04:00+00:00',
      content: '已经定位信号聚合过宽',
      raw_available: true,
    },
  ],
  hits: [
    {
      fact_id: 'risk-alpha',
      category: 'high_risk_operation',
      fact_type: 'risk',
      severity: 'high',
      occurred_at: '2026-06-21T01:03:00+00:00',
      summary: '命中高风险操作',
      content_preview: '高风险操作: 工作区文件',
    },
    {
      fact_id: 'tool-alpha',
      category: 'tool_call',
      fact_type: 'tool',
      severity: 'low',
      occurred_at: '2026-06-21T01:03:10+00:00',
      summary: 'Codex 调用工具 exec_command，类别 function_call，已提取工具调用摘要。',
      content_preview: '工具 exec_command',
    },
  ],
};

const response: ConversationsResponse = {
  conversations: [detail],
  total: 1,
  page: 1,
  page_size: 50,
  has_more: false,
  window: '1h',
};

describe('ConversationQueryPage', () => {
  it('renders conversations and searches prompt and response keywords on submit', async () => {
    const user = userEvent.setup();
    const loadConversations = vi.fn(async () => response);
    render(
      <ConversationQueryPage
        loadConversationDetail={async () => detail}
        loadConversationForFact={async () => detail}
        loadConversations={loadConversations}
      />
    );

    expect(await screen.findByText('序号')).toBeInTheDocument();
    expect(screen.getByText('时间戳')).toBeInTheDocument();
    expect(screen.getAllByText('提交 Prompt').length).toBeGreaterThan(0);
    expect(screen.getAllByText('响应内容').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '时间范围：1小时' })).toBeInTheDocument();
    expect(loadConversations).toHaveBeenCalledWith({
      window: '1h',
      start_at: '',
      end_at: '',
      prompt_query: '',
      response_query: '',
      page: 1,
      page_size: 50,
    });

    await user.type(screen.getByLabelText('提交 Prompt'), '观测');
    expect(loadConversations).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: '搜索会话' }));
    await waitFor(() => expect(loadConversations).toHaveBeenLastCalledWith(expect.objectContaining({ prompt_query: '观测' })));
    await user.type(screen.getByLabelText('响应内容'), '信号');
    expect(loadConversations).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: '时间范围：1小时' }));
    await user.click(screen.getByRole('button', { name: '2小时' }));
    expect(loadConversations).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: '时间范围：2小时' }));
    await user.type(screen.getByLabelText('开始'), '2026-06-21T09:30:15');
    await user.type(screen.getByLabelText('结束'), '2026-06-21T10:30:45');
    expect(loadConversations).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: '确认' }));
    expect(screen.getByText(/06\/21 09:30:15 - 10:30:45/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '搜索会话' }));
    const expectedStart = new Date('2026-06-21T09:30:15').toISOString();
    const expectedEnd = new Date('2026-06-21T10:30:45').toISOString();
    await waitFor(() => expect(loadConversations).toHaveBeenLastCalledWith(expect.objectContaining({
      prompt_query: '观测',
      response_query: '信号',
      start_at: expectedStart,
      end_at: expectedEnd,
      window: '',
    })));
  });

  it('opens the conversation drawer from a row and from an initial fact', async () => {
    const user = userEvent.setup();
    const loadConversationForFact = vi.fn(async () => detail);
    render(
      <ConversationQueryPage
        initialFactId="risk-alpha"
        loadConversationDetail={async () => detail}
        loadConversationForFact={loadConversationForFact}
        loadConversations={async () => response}
      />
    );

    expect(await screen.findByLabelText('会话详情')).toBeInTheDocument();
    expect(loadConversationForFact).toHaveBeenCalledWith('risk-alpha');
    expect(screen.getByText('模型调用累计有效 token')).toBeInTheDocument();
    expect(screen.getByText('缓存命中 token')).toBeInTheDocument();
    expect(screen.getByText('60.0%')).toBeInTheDocument();
    expect(screen.getByText('检测到高风险操作：工作区文件')).toBeInTheDocument();
    expect(screen.getByText('其他技术活动已折叠')).toBeInTheDocument();
    expect(screen.queryByText('工具 exec_command')).not.toBeInTheDocument();
    await user.click(screen.getByLabelText('关闭会话详情'));
    await user.click(screen.getByRole('row', { name: /请检查观测总览/ }));
    expect((await screen.findAllByText('已经定位信号聚合过宽')).length).toBeGreaterThan(0);
  });

  it('shows the return action when opened from a signal', async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    render(
      <ConversationQueryPage
        backLabel="返回信号"
        loadConversationDetail={async () => detail}
        loadConversationForFact={async () => detail}
        loadConversations={async () => response}
        onBack={onBack}
      />
    );

    await user.click(await screen.findByRole('button', { name: /返回信号/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
