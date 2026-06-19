import { ArrowRight } from 'lucide-react';

import type { ObservationStory } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import {
  attentionStateLabel,
  compactListSummary,
  diagnosticStatusLabel,
  evidenceSummary,
  handlingStateLabel,
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
          <dt>证据链</dt>
          <dd>{evidenceSummary(story.evidence_refs)}</dd>
        </div>
        <div>
          <dt>用量</dt>
          <dd>{usageSummaryText(story.usage_summary)}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>
            {attentionStateLabel(story.attention_state)}，{handlingStateLabel(story.handling_state)}
          </dd>
        </div>
        <div>
          <dt>补证</dt>
          <dd>{diagnosticStatusLabel(story.diagnostic_status_summary.status)}</dd>
        </div>
      </dl>

      <div className="story-card__footer">
        <button className="compact-button primary" onClick={() => onOpen(story.story_id)}>
          处理
          <ArrowRight aria-hidden="true" size={15} />
        </button>
      </div>
    </article>
  );
}
