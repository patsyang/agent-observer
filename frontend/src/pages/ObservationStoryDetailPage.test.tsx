import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ObservationStoryDetail } from '../api/types';
import { ObservationStoryDetailPage } from './ObservationStoryDetailPage';

const detail: ObservationStoryDetail = {
  story_id: 'story-001',
  story_key: 'error:sig-checkout-failure',
  conclusion: 'Codex command failed repeatedly in checkout workflow',
  impact_objects: ['checkout workflow'],
  evidence_refs: ['proj-error-001', 'proj-risk-001'],
  usage_summary: { attributed_units: 55, associated_units: 0, no_usage_reason: null },
  diagnostic_status_summary: { status: 'none', reason_code: null },
  handling_state: 'unread',
  conclusion_code: null,
  handling_note: null,
  attention_state: 'active',
  priority_score: 92,
  suggested_action: '查看证据链并选择处理结论',
  snapshot_hash: 'hash-story-001',
  current_snapshot: {
    evidence_chain: [
      {
        evidence_ref: 'proj-codex-02edaded9950d3c0d38',
        fact_id: 'event-error-001',
        category: 'codex_error',
        summary: '已生成错误指纹',
        quality: 'high',
        occurred_at: '2026-06-18T10:00:00+00:00',
        fact_type: 'error',
        source_event_type: 'tool_result',
        source_label: 'Codex 会话 conversation-story',
        content_preview: '工具 shell_command，退出码 1',
        raw_available: true,
        raw_status: '已上传原文'
      },
      {
        evidence_ref: 'proj-windows-collector-3fab376c2f011936df76',
        fact_id: 'event-risk-001',
        category: 'high_risk_operation',
        summary: 'Configuration touched',
        quality: 'low',
        occurred_at: '2026-06-18T10:10:00+00:00',
        fact_type: 'risk',
        source_event_type: 'tool_result',
        source_label: 'Codex 会话 conversation-story',
        content_preview: '高风险操作: 配置对象',
        raw_available: false,
        raw_status: '仅结构化字段',
        risk_object: '配置对象',
        risk_object_type: 'configuration',
        risk_category_count: 1,
        sensitive_categories: ['auth']
      }
    ],
    source_refs: [{ conversation_ref: 'conversation-story' }]
  },
  recent_audit_summary: { latest: '暂无审计记录', events: [] }
};

describe('ObservationStoryDetailPage', () => {
  const diagnosticProps = {
    loadDiagnosticAvailability: async () => ({
      capabilities: [
        {
          capability_id: 'codex_error_context',
          label: 'Collect Codex error context',
          state: 'available' as const,
          reason_code: null
        }
      ]
    }),
    requestDiagnostic: async () => ({
      job_id: 'diag-job-001',
      status: 'pending',
      capability_id: 'codex_error_context'
    }),
    cancelDiagnostic: async () => ({
      job_id: 'diag-job-001',
      status: 'cancelled',
      capability_id: 'codex_error_context'
    })
  };

  it('renders story detail evidence chain, usage, diagnostic state and audit summary', async () => {
    const loadStoryDetail = vi.fn(async () => detail);
    const loadDiagnosticAvailability = vi.fn(diagnosticProps.loadDiagnosticAvailability);
    const openFact = vi.fn();
    render(
      <ObservationStoryDetailPage
        storyId="story-001"
        loadStoryDetail={loadStoryDetail}
        loadDiagnosticAvailability={loadDiagnosticAvailability}
        requestDiagnostic={diagnosticProps.requestDiagnostic}
        cancelDiagnostic={diagnosticProps.cancelDiagnostic}
        markRead={async () => detail}
        handleStory={async () => detail}
        onOpenFact={openFact}
        onBack={() => {}}
      />
    );

    expect(await screen.findByText(detail.conclusion)).toBeInTheDocument();
    const evidenceChain = screen.getByLabelText('证据链');
    expect(evidenceChain).toHaveTextContent('真实证据');
    expect(evidenceChain).toHaveTextContent('类型 / 来源');
    expect(evidenceChain).toHaveTextContent('可信度 / 原文');
    expect(evidenceChain).toHaveTextContent('Codex 错误');
    expect(evidenceChain).toHaveTextContent('Codex 会话 conversation-story');
    expect(evidenceChain).toHaveTextContent('工具 shell_command，退出码 1');
    expect(evidenceChain).toHaveTextContent('高风险操作: 配置对象');
    expect(evidenceChain).toHaveTextContent('命中 1 类线索');
    expect(evidenceChain).toHaveTextContent('命中 auth');
    expect(evidenceChain).toHaveTextContent('高可信');
    expect(evidenceChain).toHaveTextContent('已上传原文');
    expect(evidenceChain).toHaveTextContent('待补证');
    expect(screen.getByRole('cell', { name: /Codex 错误/ })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button', { name: '查看事实' })[0]);
    expect(openFact).toHaveBeenCalledWith('event-error-001');
    const summary = screen.getByLabelText('故事摘要');
    expect(summary).toHaveTextContent(/已归因 55，关联 0/);
    expect(summary).toHaveTextContent(/暂无诊断/);
    expect(screen.getByText(/暂无审计记录/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '补充上下文' }));
    expect(await screen.findByRole('status')).toHaveTextContent(/诊断 排队中/);
    expect(loadStoryDetail).toHaveBeenCalledTimes(2);
    expect(loadDiagnosticAvailability).toHaveBeenCalledTimes(2);
  });

  it('requires structured conclusion before handling and renders refreshed audit state', async () => {
    const handled: ObservationStoryDetail = {
      ...detail,
      handling_state: 'handled',
      attention_state: 'handled_hidden',
      conclusion_code: 'known_issue',
      handling_note: 'Tracked in backlog',
      recent_audit_summary: {
        latest: 'story_handling_changed by fixed-management-account at 2026-06-18T11:00:00+00:00',
        events: [
          {
            action: 'story_handling_changed',
            actor: 'fixed-management-account',
            created_at: '2026-06-18T11:00:00+00:00',
            metadata: { reason_code: 'operator_handled' }
          }
        ]
      }
    };
    render(
      <ObservationStoryDetailPage
        storyId="story-001"
        loadStoryDetail={async () => detail}
        {...diagnosticProps}
        markRead={async () => detail}
        handleStory={async () => handled}
        onBack={() => {}}
      />
    );

    await screen.findByText(detail.conclusion);
    await userEvent.click(screen.getByRole('button', { name: /处理故事/ }));
    await userEvent.click(screen.getByRole('button', { name: /^处理$/ }));
    expect(screen.getByRole('alert')).toHaveTextContent(/必须选择结构化结论/);

    await userEvent.selectOptions(screen.getByLabelText(/结论/), 'known_issue');
    await userEvent.type(screen.getByLabelText(/备注/), 'Tracked in backlog');
    await userEvent.click(screen.getByRole('button', { name: /^处理$/ }));

    expect(await screen.findByText(/已处理隐藏，已处理，已知问题/)).toBeInTheDocument();
    expect(screen.getByText(/Tracked in backlog/)).toBeInTheDocument();
    expect(screen.getByText(/story_handling_changed by fixed-management-account/)).toBeInTheDocument();
    expect(screen.getByText(/operator_handled/)).toBeInTheDocument();
  });
});
