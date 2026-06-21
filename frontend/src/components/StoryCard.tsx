import { ArrowRight } from 'lucide-react';

import type { ObservationStory } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import {
  attentionStateLabel,
  compactListSummary,
  enrichmentStatusLabel,
  handlingStateLabel,
  storyEvidenceSummary,
  storyKindLabel,
  usageSummaryText,
} from './storyLabels';

interface Props {
  story: ObservationStory;
  onOpen: (storyId: string) => void;
}

export function StoryCard({ story, onOpen }: Props) {
  return (
    <article className="story-card" data-story-key={story.story_key}>
      <div className="story-card__header">
        <div>
          <div className="story-card__badges">
            <span className="badge violet">{storyKindLabel(story.story_key)}</span>
            <span className="badge gray">优先级 {formatNumber(story.priority_score)}</span>
            <span className="badge teal">最近 {formatStoryTime(story.last_event_at)}</span>
          </div>
          <h3>{story.conclusion}</h3>
          <small>{story.suggested_action}</small>
        </div>
      </div>

      <dl className="story-fields story-fields--compact">
        <div>
          <dt>影响范围</dt>
          <dd>{compactListSummary(story.impact_objects, '对象')}</dd>
        </div>
        <div>
          <dt>命中内容</dt>
          <dd>{storyEvidenceSummary(story)}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>
            {attentionStateLabel(story.attention_state)}，{handlingStateLabel(story.handling_state)}
          </dd>
        </div>
        <div>
          <dt>次数</dt>
          <dd>{formatNumber(story.occurrence_count ?? story.evidence_refs.length)} 次</dd>
        </div>
        <div>
          <dt>用量</dt>
          <dd>{usageSummaryText(story.usage_summary)}</dd>
        </div>
        <div>
          <dt>补证</dt>
          <dd>{enrichmentStatusLabel(story.enrichment_status_summary.status)}</dd>
        </div>
      </dl>

      <div className="story-card__footer">
        <button className="compact-button primary" onClick={() => onOpen(story.story_id)}>
          查看信号
          <ArrowRight aria-hidden="true" size={15} />
        </button>
      </div>
    </article>
  );
}

function formatStoryTime(value?: string | null): string {
  if (!value) return '暂无时间';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
