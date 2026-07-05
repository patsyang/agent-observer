import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { BehaviorSignalDetail } from '../api/types';
import { SignalDetailPage } from './SignalDetailPage';

const detail: BehaviorSignalDetail = {
  signal_id: 'signal-001',
  signal_key: 'change_volume_anomaly:conversation-1',
  signal_kind: 'change_volume_anomaly',
  risk_family: 'behavior_anomaly',
  title: '单会话变更量异常：22 个文件',
  why_it_matters: '单个会话里产生大范围文件修改。',
  severity: 'medium',
  confidence: 'high',
  priority_score: 75,
  affected_scope: { conversation_count: 1, operation_count: 22, file_count: 12 },
  evidence_groups: [
    {
      group_id: 'failure:tool-events',
      group_type: 'failure',
      title: '命中事件',
      summary: '1 条命中',
      count: 22,
      items: [{
        evidence_ref: 'fact-1',
        fact_id: 'fact-1',
        category: 'file_change',
        quality: 'high',
        fact_type: 'risk',
        source_event_type: 'tool_call',
        source_label: 'Codex 会话 conversation-1',
        occurred_at: '2026-06-21T10:00:00Z',
        summary: '工具执行失败：cmd /c apps\\agent-observer\\scripts\\start-backend.cmd，exit_code=1。',
        content_preview: '命令 cmd /c apps\\agent-observer\\scripts\\start-backend.cmd，退出码 1',
        tool_context: {
          tool_name: 'exec_command',
          command: 'cmd /c apps\\agent-observer\\scripts\\start-backend.cmd',
          command_excerpt: 'cmd /c apps\\agent-observer\\scripts\\start-backend.cmd',
          command_category: 'shell',
          exit_code: 1,
          is_timeout: false,
          timeout_ms: null,
          timeout_after_ms: null,
          wall_time_seconds: null,
          error_excerpt: 'Port 8765 is already in use.',
          call_id: ''
        }
      }]
    }
  ],
  linked_conversations: [{
    conversation_ref: 'conversation-1',
    session_ref: 'session-1',
    session_title: '重构信号详情页',
    workspace: {
      workspace_id: 'codex:agent-observer',
      workspace_path: 'D:/workspace/agentic_factory/apps/agent-observer',
      workspace_label: 'Agent Observer'
    },
    hit_count: 22,
    last_seen_at: '2026-06-21T10:00:00Z',
    matched_fact_ids: ['fact-1']
  }],
  workspace_refs: [{
    agent_type: 'codex',
    workspace_id: 'codex:agent-observer',
    workspace_path: 'D:/workspace/agentic_factory/apps/agent-observer',
    workspace_label: 'Agent Observer',
    workspace_alias_source: 'codex_global_state',
    workspace_confidence: 'high'
  }],
  workspace_summary: { mode: 'single', label: 'Agent Observer', count: 1 },
  usage_summary: { effective_units: 0, no_usage_reason: '没有用量证据' },
  enrichment_status_summary: { status: 'none', reason_code: null },
  suggested_actions: ['打开关联会话核对任务边界'],
  decision_state: 'unread',
  conclusion_code: null,
  note: null,
  snapshot_hash: 'hash',
  occurrence_count: 22
};

describe('SignalDetailPage', () => {
  it('renders grouped evidence instead of a flat hit table', async () => {
    const user = userEvent.setup();
    render(
      <SignalDetailPage
        signalId="signal-001"
        loadSignalDetail={async () => detail}
        loadConversationDetail={async () => ({
          conversation_ref: 'conversation-1',
          session_ref: 'session-1',
          session_title: '重构信号详情页',
          agent_type: 'codex',
          source_id: 'codex-local',
          source_kind: 'codex_local',
          workspace: detail.workspace_refs[0],
          started_at: '2026-06-21T09:00:00Z',
          last_event_at: '2026-06-21T10:00:00Z',
          prompt_preview: '检查信号详情页',
          response_preview: '已定位命中内容',
          event_count: 2,
          hit_count: 1,
          token_usage: { effective_units: 120, cached_input_units: 40, input_token_units: 100, cache_hit_rate: 0.4 },
          messages: [],
          hits: [{
            fact_id: 'fact-1',
            category: 'tool_execution_failure',
            fact_type: 'error',
            severity: 'medium',
            occurred_at: '2026-06-21T10:00:00Z',
            summary: '工具执行失败：cmd /c apps\\agent-observer\\scripts\\start-backend.cmd，exit_code=1。',
            content_preview: '命令 cmd /c apps\\agent-observer\\scripts\\start-backend.cmd，退出码 1',
            tool_context: {
              tool_name: 'exec_command',
              command: 'cmd /c apps\\agent-observer\\scripts\\start-backend.cmd',
              command_excerpt: 'cmd /c apps\\agent-observer\\scripts\\start-backend.cmd',
              command_category: 'shell',
              exit_code: 1,
              is_timeout: false,
              timeout_ms: null,
              timeout_after_ms: null,
              wall_time_seconds: null,
              error_excerpt: 'Port 8765 is already in use.',
              call_id: ''
            }
          }]
        })}
        loadEnrichmentAvailability={async () => ({ capabilities: [] })}
        markRead={async () => detail}
        handleSignal={async () => detail}
        requestEnrichment={async () => ({ job_id: 'job-1', status: 'queued', capability_id: 'codex_tool_failure_context' })}
        cancelEnrichment={async () => ({ job_id: 'job-1', status: 'cancelled', capability_id: 'codex_tool_failure_context' })}
        onBack={() => {}}
      />
    );

    await waitFor(() => expect(screen.getByText(detail.title)).toBeInTheDocument());
    expect(screen.getByText('判断依据')).toBeInTheDocument();
    expect(screen.queryByText('为什么重要')).not.toBeInTheDocument();
    expect(screen.getAllByText('Agent Observer').length).toBeGreaterThan(0);
    expect(screen.getByText('D:/workspace/agentic_factory/apps/agent-observer')).toBeInTheDocument();
    expect(screen.getByText('重构信号详情页')).toBeInTheDocument();
    expect(screen.queryByText('codex_global_state')).not.toBeInTheDocument();
    expect(screen.getByTestId('evidence-groups')).toHaveTextContent('命中事件');
    expect(screen.getByTestId('evidence-groups')).not.toHaveTextContent('会话 conversation-1');
    expect(screen.getByText('命令：cmd /c apps\\agent-observer\\scripts\\start-backend.cmd')).toBeInTheDocument();
    expect(screen.getByText('错误摘要：Port 8765 is already in use.')).toBeInTheDocument();
    expect(screen.queryByTestId('evidence-chain')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /重构信号详情页/ }));
    const drawer = await screen.findByLabelText('会话详情');
    expect(within(drawer).getByText('当前信号命中')).toBeInTheDocument();
    expect(within(drawer).getByText('命令：cmd /c apps\\agent-observer\\scripts\\start-backend.cmd')).toBeInTheDocument();
    expect(within(drawer).getByText('错误摘要：Port 8765 is already in use.')).toBeInTheDocument();
  });
});
