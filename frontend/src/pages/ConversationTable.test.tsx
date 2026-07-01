import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ConversationSummary } from '../api/types';
import { ConversationTable } from './ConversationTable';

function makeRow(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversation_ref: 'conv-1',
    session_ref: 'session-1',
    session_title: '示例会话',
    agent_type: 'codex',
    source_id: 'codex-local',
    source_kind: 'codex_local',
    workspace: {
      workspace_id: 'codex:demo',
      workspace_path: 'D:/workspace/demo',
      workspace_label: 'Demo',
    },
    started_at: '2026-06-21T01:00:00+00:00',
    last_event_at: '2026-06-21T01:04:00+00:00',
    prompt_preview: '请检查观测总览',
    response_preview: '已经定位问题',
    event_count: 3,
    hit_count: 0,
    token_usage: {
      effective_units: 320,
    },
    ...overrides,
  };
}

const meta = { total: 1, page: 1, page_size: 20, has_more: false };

describe('ConversationTable', () => {
  it('renders Claude Code as the source label for claude conversations', () => {
    render(
      <ConversationTable
        meta={meta}
        onOpen={vi.fn()}
        onPage={vi.fn()}
        rows={[makeRow({ conversation_ref: 'conv-claude', agent_type: 'claude' })]}
      />
    );

    expect(screen.getByRole('columnheader', { name: '来源' })).toBeInTheDocument();
    expect(screen.getByText('Claude Code')).toBeInTheDocument();
  });

  it('renders Codex as the source label for codex conversations to prevent regression', () => {
    render(
      <ConversationTable
        meta={meta}
        onOpen={vi.fn()}
        onPage={vi.fn()}
        rows={[makeRow({ conversation_ref: 'conv-codex', agent_type: 'codex' })]}
      />
    );

    expect(screen.getByText('Codex')).toBeInTheDocument();
    expect(screen.queryByText('Claude Code')).not.toBeInTheDocument();
  });
});
