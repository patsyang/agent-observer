import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { BehaviorSignal } from '../api/types';
import { SignalCard } from './SignalCard';

const signal: BehaviorSignal = {
  signal_id: 'signal-001',
  signal_key: 'tool_failure_cluster:function_call_output:1',
  signal_kind: 'tool_failure_cluster',
  title: '工具失败集中出现：exec / exit_code 1',
  why_it_matters: '同类工具失败在多个会话中出现。',
  severity: 'high',
  confidence: 'high',
  priority_score: 95,
  affected_scope: { conversation_count: 2, failure_count: 5 },
  evidence_groups: [{ group_id: 'failure:1', group_type: 'failure', title: '失败类型', summary: '5 条', count: 5, items: [] }],
  linked_conversations: [],
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
    await userEvent.click(screen.getByTestId('open-signal'));
    expect(onOpen).toHaveBeenCalledWith('signal-001');
  });
});

