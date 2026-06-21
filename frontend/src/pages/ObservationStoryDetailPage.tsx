import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { EnrichmentPanel } from '../components/EnrichmentPanel';
import { EvidenceChainTable } from '../components/EvidenceChainTable';
import { HandleStoryDialog } from '../components/HandleStoryDialog';
import {
  attentionStateLabel,
  conclusionCodeLabel,
  enrichmentStatusLabel,
  handlingStateLabel,
  storyKindLabel,
  usageSummaryText,
} from '../components/storyLabels';
import type { EnrichmentAvailability, EnrichmentJob, HandleStoryPayload, ObservationStoryDetail } from '../api/types';

interface Props {
  storyId: string;
  loadStoryDetail: (storyId: string) => Promise<ObservationStoryDetail>;
  loadEnrichmentAvailability: (storyId: string) => Promise<EnrichmentAvailability>;
  markRead: (storyId: string) => Promise<ObservationStoryDetail>;
  handleStory: (storyId: string, payload: HandleStoryPayload) => Promise<ObservationStoryDetail>;
  requestEnrichment: (storyId: string, capabilityId: string) => Promise<EnrichmentJob>;
  cancelEnrichment: (jobId: string) => Promise<EnrichmentJob>;
  onBack: () => void;
  onOpenFact?: (factId: string) => void;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; story: ObservationStoryDetail; enrichmentAvailability: EnrichmentAvailability };

export function ObservationStoryDetailPage({
  storyId,
  loadStoryDetail,
  loadEnrichmentAvailability,
  markRead,
  handleStory,
  requestEnrichment,
  cancelEnrichment,
  onBack,
  onOpenFact
}: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [story, enrichmentAvailability] = await Promise.all([
      loadStoryDetail(storyId),
      loadEnrichmentAvailability(storyId),
    ]);
    setState({ status: 'ready', story, enrichmentAvailability });
  }, [loadEnrichmentAvailability, loadStoryDetail, storyId]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadStoryDetail(storyId), loadEnrichmentAvailability(storyId)])
      .then(([story, enrichmentAvailability]) => {
        if (!cancelled) setState({ status: 'ready', story, enrichmentAvailability });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [loadEnrichmentAvailability, loadStoryDetail, storyId]);

  if (state.status === 'loading') {
    return <section className="panel">正在加载信号详情</section>;
  }
  if (state.status === 'error') {
    return (
      <section className="panel">
        <p>信号详情不可用。</p>
        <button onClick={onBack}>返回总览</button>
      </section>
    );
  }

  const { enrichmentAvailability, story } = state;
  return (
    <section className="panel story-detail" aria-label="信号详情">
      <header className="detail-header">
        <div>
          <h2>{story.conclusion}</h2>
          <p>信号类型：{storyKindLabel(story.story_key)}</p>
        </div>
        <div className="detail-header__actions">
          <button className="compact-button" onClick={reload} type="button">
            <RefreshCw aria-hidden="true" size={15} />
            刷新
          </button>
          <button className="compact-button" onClick={onBack} type="button">
            <ArrowLeft aria-hidden="true" size={15} />
            返回总览
          </button>
        </div>
      </header>
      <div className="action-row">
        <button
          disabled={story.handling_state !== 'unread'}
          onClick={() => runMutation(() => markRead(story.story_id))}
        >
          标记已读
        </button>
        <button className="primary" onClick={() => setDialogOpen(true)}>
          处理信号
        </button>
      </div>
      {mutationError && <p role="alert">{mutationError}</p>}
      {dialogOpen && (
        <HandleStoryDialog
          onCancel={() => setDialogOpen(false)}
          onSubmit={async (payload) => {
            await runMutation(() => handleStory(story.story_id, payload));
            setDialogOpen(false);
          }}
        />
      )}
      <div className="detail-summary" aria-label="信号摘要">
        <div>
          <span>影响对象</span>
          <strong>{story.impact_objects.join(', ')}</strong>
        </div>
        <div>
          <span>状态</span>
          <strong>
            {attentionStateLabel(story.attention_state)}，{handlingStateLabel(story.handling_state)}
            {story.conclusion_code ? `，${conclusionCodeLabel(story.conclusion_code)}` : ''}
          </strong>
          {story.handling_note && <small>{story.handling_note}</small>}
        </div>
        <div>
          <span>用量</span>
          <strong>{usageSummaryText(story.usage_summary)}</strong>
        </div>
        <div>
          <span>补证</span>
          <strong>
            {enrichmentStatusLabel(story.enrichment_status_summary.status)}
            {story.enrichment_status_summary.reason_code ? `，${story.enrichment_status_summary.reason_code}` : ''}
          </strong>
        </div>
      </div>
      <EnrichmentPanel
        storyId={story.story_id}
        availability={enrichmentAvailability}
        requestEnrichment={requestEnrichment}
        cancelEnrichment={cancelEnrichment}
        onChanged={reload}
      />
      <section aria-label="证据链">
        <h3>命中内容</h3>
        <p className="panel-intro">以下为本信号命中的内容。点击“查看会话”会打开所属会话的完整输入输出和 token 用量。</p>
        <EvidenceChainTable entries={story.current_snapshot.evidence_chain} onOpenFact={onOpenFact} />
      </section>
      <section>
        <h3>最近审计</h3>
        <p>{story.recent_audit_summary.latest}</p>
        <ul>
          {story.recent_audit_summary.events.map((event) => (
            <li key={`${event.action}-${event.created_at}`}>
              {event.action}: {String(event.metadata.reason_code ?? '状态已变化')}
            </li>
          ))}
        </ul>
      </section>
    </section>
  );

  async function runMutation(action: () => Promise<ObservationStoryDetail>) {
    setMutationError(null);
    try {
      setState({ status: 'ready', story: await action(), enrichmentAvailability });
    } catch {
      setMutationError('信号操作失败。请刷新后重试。');
    }
  }
}
