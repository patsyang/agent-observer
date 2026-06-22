import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { BehaviorSignal } from '../api/types';
import { SignalCard } from './SignalCard';

const signal: BehaviorSignal = {
  signal_id: 'signal-001',
  signal_key: 'tool_execution_failure:exec_command:1',
  signal_kind: 'tool_execution_failure',
  title: '工具执行失败：exec / exit_code 1',
  why_it_matters: '同类工具失败在多个会话中出现。',
  severity: 'high',
  confidence: 'high',
  priority_score: 95,
  affected_scope: { conversation_count: 2, failure_count: 5 },
  evidence_groups: [{
    group_id: 'failure:1',
    group_type: 'failure',
    title: '失败类型',
    summary: '5 条',
    count: 5,
    items: [{
      evidence_ref: 'fact:1',
      fact_id: 'fact-1',
      category: 'tool_execution_failure',
      quality: 'high',
      fact_type: 'error',
      summary: '工具执行失败',
      source_event_type: 'function_call_output',
      source_label: '会话',
      tool_context: {
        tool_name: 'function_call_output',
        command: 'function_call_output --exit-code 1 --local-port 5173 --state listen',
        command_excerpt: 'function_call_output, exit_code=1',
        command_category: 'shell',
        exit_code: 1,
        is_timeout: false,
        timeout_ms: null,
        timeout_after_ms: null,
        wall_time_seconds: 1,
        error_excerpt: 'LocalAddress LocalPort State OwningProcess 127.0.0.1 5173 Listen',
        call_id: 'call-1'
      }
    }]
  }],
  linked_conversations: [],
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
  suggested_actions: ['补充工具失败上下文'],
  decision_state: 'unread',
  conclusion_code: null,
  note: null,
  snapshot_hash: 'hash',
  occurrence_count: 5
};

describe('SignalCard', () => {
  it('renders risk title and opens by signal id', async () => {
    const onOpen = vi.fn();
    render(<SignalCard signal={signal} onOpen={onOpen} />);

    expect(screen.getByText(signal.title)).toBeInTheDocument();
    expect(screen.getByText(signal.why_it_matters)).toBeInTheDocument();
    expect(screen.getByText('Agent Observer')).toBeInTheDocument();
    expect(screen.getByTestId('signal-card-meta')).toHaveTextContent('命中');
    expect(screen.getByTestId('signal-card-context')).toHaveTextContent('function_call_output, exit_code=1');
    expect(screen.getByTestId('signal-card-context')).toHaveTextContent('LocalAddress LocalPort');
    await userEvent.click(screen.getByTestId('open-signal'));
    expect(onOpen).toHaveBeenCalledWith('signal-001');
  });
});
