import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { DiagnosticPanel } from '../components/DiagnosticPanel';
import { EvidenceChainTable } from '../components/EvidenceChainTable';
import { HandleStoryDialog } from '../components/HandleStoryDialog';
import {
  attentionStateLabel,
  conclusionCodeLabel,
  diagnosticStatusLabel,
  handlingStateLabel,
  storyKindLabel,
  usageSummaryText,
} from '../components/storyLabels';
import type { DiagnosticAvailability, DiagnosticJob, HandleStoryPayload, ObservationStoryDetail } from '../api/types';

interface Props {
  storyId: string;
  loadStoryDetail: (storyId: string) => Promise<ObservationStoryDetail>;
  loadDiagnosticAvailability: (storyId: string) => Promise<DiagnosticAvailability>;
  markRead: (storyId: string) => Promise<ObservationStoryDetail>;
  handleStory: (storyId: string, payload: HandleStoryPayload) => Promise<ObservationStoryDetail>;
  requestDiagnostic: (storyId: string, capabilityId: string) => Promise<DiagnosticJob>;
  cancelDiagnostic: (jobId: string) => Promise<DiagnosticJob>;
  onBack: () => void;
  onOpenFact?: (factId: string) => void;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; story: ObservationStoryDetail; diagnosticAvailability: DiagnosticAvailability };

export function ObservationStoryDetailPage({
  storyId,
  loadStoryDetail,
  loadDiagnosticAvailability,
  markRead,
  handleStory,
  requestDiagnostic,
  cancelDiagnostic,
  onBack,
  onOpenFact
}: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [story, diagnosticAvailability] = await Promise.all([
      loadStoryDetail(storyId),
      loadDiagnosticAvailability(storyId),
    ]);
    setState({ status: 'ready', story, diagnosticAvailability });
  }, [loadDiagnosticAvailability, loadStoryDetail, storyId]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadStoryDetail(storyId), loadDiagnosticAvailability(storyId)])
      .then(([story, diagnosticAvailability]) => {
        if (!cancelled) setState({ status: 'ready', story, diagnosticAvailability });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [loadDiagnosticAvailability, loadStoryDetail, storyId]);

  if (state.status === 'loading') {
    return <section className="panel">正在加载故事详情</section>;
  }
  if (state.status === 'error') {
    return (
      <section className="panel">
        <p>故事详情不可用。</p>
        <button onClick={onBack}>返回总览</button>
      </section>
    );
  }

  const { diagnosticAvailability, story } = state;
  const usageText = usageSummaryText(story.usage_summary);

  return (
    <section className="panel story-detail" aria-label="故事详情">
      <header className="detail-header">
        <div>
          <h2>{story.conclusion}</h2>
          <p>故事类型：{storyKindLabel(story.story_key)}</p>
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
          处理故事
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
      <div className="detail-summary" aria-label="故事摘要">
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
          <strong>{usageText}</strong>
        </div>
        <div>
          <span>诊断</span>
          <strong>
            {diagnosticStatusLabel(story.diagnostic_status_summary.status)}
            {story.diagnostic_status_summary.reason_code ? `，${story.diagnostic_status_summary.reason_code}` : ''}
          </strong>
        </div>
      </div>
      <DiagnosticPanel
        storyId={story.story_id}
        availability={diagnosticAvailability}
        requestDiagnostic={requestDiagnostic}
        cancelDiagnostic={cancelDiagnostic}
        onChanged={reload}
      />
      <section aria-label="证据链">
        <h3>证据链</h3>
        <p className="panel-intro">以下为本故事使用的真实事实。点击“查看事实”可打开完整原文、投影字段和来源位置。</p>
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
      setState({ status: 'ready', story: await action(), diagnosticAvailability });
    } catch {
      setMutationError('故事操作失败。请刷新后重试。');
    }
  }
}
