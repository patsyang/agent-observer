import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { McpCallsResponse } from '../api/types';
import { McpObservationPage } from './McpObservationPage';

const mockResponse: McpCallsResponse = {
  items: [
    {
      fact_id: 'fact-1',
      occurred_at: '2026-07-12T10:00:00Z',
      conversation_ref: 'conv-1',
      mcp_server: 'filesystem',
      mcp_tool: 'read_file',
      mcp_duration_ms: 42,
      mcp_is_error: false,
      mcp_args_summary: '读取 /etc/config.yaml',
      arguments: [{ key: 'path', value: '/etc/config.yaml' }, { key: 'encoding', value: 'utf-8' }],
      result_text: 'file content here',
      risk_signals: []
    },
    {
      fact_id: 'fact-2',
      occurred_at: '2026-07-12T10:05:00Z',
      conversation_ref: 'conv-2',
      mcp_server: 'github',
      mcp_tool: 'create_issue',
      mcp_duration_ms: 120,
      mcp_is_error: true,
      mcp_args_summary: '创建 Issue: 修复登录问题',
      arguments: [{ key: 'title', value: '修复登录问题' }, { key: 'body', value: '详细描述' }],
      result_text: 'Error: permission denied',
      risk_signals: [{ risk_type: 'destructive_operation', severity: 'high', object_type: 'file' }]
    }
  ],
  total: 2,
  page: 1,
  page_size: 20,
  summary: {
    servers: ['filesystem', 'github'],
    total_calls: 2,
    error_calls: 1,
    risk_calls: 1
  }
};

describe('McpObservationPage', () => {
  it('renders summary cards and call table from API data', async () => {
    const loadMcpCalls = vi.fn(async () => mockResponse);
    render(<McpObservationPage loadMcpCalls={loadMcpCalls} />);

    // 等待数据行出现（表示数据已加载），再检查 metric
    const rows = await screen.findAllByTestId('mcp-call-row');
    expect(rows).toHaveLength(2);
    expect(screen.getByTestId('mcp-summary-servers')).toHaveTextContent('2');
    expect(screen.getByTestId('mcp-summary-total')).toHaveTextContent('2');
    expect(screen.getByTestId('mcp-summary-errors')).toHaveTextContent('1');
    expect(screen.getByTestId('mcp-summary-risks')).toHaveTextContent('1');

    expect(screen.getByText('read_file')).toBeInTheDocument();
    expect(screen.getByText('create_issue')).toBeInTheDocument();
  });

  it('expands row to show arguments, result and risk signals', async () => {
    const user = userEvent.setup();
    const loadMcpCalls = vi.fn(async () => mockResponse);
    render(<McpObservationPage loadMcpCalls={loadMcpCalls} />);

    const rows = await screen.findAllByTestId('mcp-call-row');
    expect(rows).toHaveLength(2);

    await user.click(rows[1]);
    const detail = await screen.findByTestId('mcp-call-detail');
    expect(within(detail).getByText('修复登录问题')).toBeInTheDocument();
    expect(within(detail).getByText('Error: permission denied')).toBeInTheDocument();
    expect(within(detail).getByText('destructive_operation')).toBeInTheDocument();
  });

  it('filters by server, risk-only and error-only flags', async () => {
    const user = userEvent.setup();
    const loadMcpCalls = vi.fn(async (params: { page?: number; page_size?: number; server?: string; risk_only?: boolean; error_only?: boolean } = {}) => mockResponse);
    render(<McpObservationPage loadMcpCalls={loadMcpCalls} />);

    // 等待数据加载完成（数据行出现）后再操作筛选器
    await screen.findAllByTestId('mcp-call-row');

    await user.selectOptions(screen.getByLabelText('MCP Server'), 'github');
    await user.click(screen.getByLabelText('仅看风险'));
    await user.click(screen.getByLabelText('仅看错误'));

    await waitFor(() => {
      const lastCall = loadMcpCalls.mock.calls.at(-1)?.[0];
      expect(lastCall?.server).toBe('github');
      expect(lastCall?.risk_only).toBe(true);
      expect(lastCall?.error_only).toBe(true);
    });
  });
});
