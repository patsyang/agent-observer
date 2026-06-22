import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { BehaviorSignalDetail } from '../api/types';
import { SignalDetailPage } from './SignalDetailPage';

const detail: BehaviorSignalDetail = {
  signal_id: 'signal-001',
  signal_key: 'workspace_change_burst:conversation-1',
  signal_kind: 'workspace_change_burst',
  title: '单会话工作区修改密集：22 次操作',
  why_it_matters: '单个会话里短时间触发大量文件修改。',
  severity: 'medium',
  confidence: 'high',
  priority_score: 75,
  affected_scope: { conversation_count: 1, operation_count: 22, file_count: 12 },
  evidence_groups: [
    {
      group_id: 'conversation:conversation-1',
      group_type: 'conversation',
      title: '会话 conversation-1',
      summary: '22 条命中',
      count: 22,
      items: [{
        evidence_ref: 'fact-1',
        fact_id: 'fact-1',
        category: 'high_risk_operation',
        quality: 'high',
        fact_type: 'risk',
        source_event_type: 'tool_call',
        source_label: 'Codex 会话 conversation-1',
        occurred_at: '2026-06-21T10:00:00Z',
        summary: '修改文件',
        content_preview: 'src/App.tsx'
      }]
    }
  ],
  linked_conversations: [{ conversation_ref: 'conversation-1', hit_count: 22, last_seen_at: '2026-06-21T10:00:00Z' }],
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
    render(
      <SignalDetailPage
        signalId="signal-001"
        loadSignalDetail={async () => detail}
        loadEnrichmentAvailability={async () => ({ capabilities: [] })}
        markRead={async () => detail}
        handleSignal={async () => detail}
        requestEnrichment={async () => ({ job_id: 'job-1', status: 'queued', capability_id: 'codex_tool_failure_context' })}
        cancelEnrichment={async () => ({ job_id: 'job-1', status: 'cancelled', capability_id: 'codex_tool_failure_context' })}
        onBack={() => {}}
      />
    );

    await waitFor(() => expect(screen.getByText(detail.title)).toBeInTheDocument());
    expect(screen.getByTestId('evidence-groups')).toHaveTextContent('会话 conversation-1');
    expect(screen.queryByTestId('evidence-chain')).not.toBeInTheDocument();
  });
});
