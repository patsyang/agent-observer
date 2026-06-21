import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ObservationStory } from '../api/types';
import { StoryCard } from './StoryCard';

const story: ObservationStory = {
  story_id: 'story-001',
  story_key: 'error:sig-checkout-failure',
  conclusion: 'Codex 命令在 checkout 流程中重复失败，已生成错误指纹。',
  impact_objects: ['checkout workflow'],
  evidence_refs: ['proj-error-001', 'proj-usage-001'],
  usage_summary: { effective_units: 55, no_usage_reason: null },
  enrichment_status_summary: { status: 'none', reason_code: null },
  handling_state: 'unread',
  conclusion_code: null,
  handling_note: null,
  attention_state: 'active',
  priority_score: 92,
  suggested_action: '查看证据链并选择处理结论',
  snapshot_hash: 'hash-story-001'
};

describe('StoryCard', () => {
  it('renders a readable signal summary without exposing projection ids as primary content', async () => {
    const onOpen = vi.fn();
    render(<StoryCard story={story} onOpen={onOpen} />);

    expect(screen.getByText(story.conclusion)).toBeInTheDocument();
    expect(screen.getAllByText(/checkout workflow/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('错误复发')).toBeInTheDocument();
    expect(screen.getByText(/2 条证据投影/)).toBeInTheDocument();
    expect(screen.queryByText(/proj-error-001/)).not.toBeInTheDocument();
    expect(screen.getByText(/有效用量 55/)).toBeInTheDocument();
    expect(screen.getByText(/未读/)).toBeInTheDocument();
    expect(screen.getByText(story.suggested_action)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '查看信号' }));
    expect(onOpen).toHaveBeenCalledWith('story-001');
  });

  it('uses the story conclusion to explain sensitive hit evidence', () => {
    render(
      <StoryCard
        story={{
          ...story,
          story_id: 'story-risk-sensitive-object-touch-credential',
          story_key: 'risk:sensitive_object_touch:credential',
          conclusion: '检测到 104 次敏感对象触达，归类为认证凭据对象；主要命中 token 72 次、auth 21 次。',
          impact_objects: ['认证凭据对象', 'Codex 对话 104 个'],
        }}
        onOpen={vi.fn()}
      />
    );

    expect(screen.getByText(/主要命中 token 72 次、auth 21 次/)).toBeInTheDocument();
    expect(screen.queryByText('敏感对象')).not.toBeInTheDocument();
  });
});
