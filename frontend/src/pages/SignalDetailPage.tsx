import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { EnrichmentPanel } from '../components/EnrichmentPanel';
import { HandleSignalDialog } from '../components/HandleSignalDialog';
import { conclusionCodeLabel, decisionStateLabel, enrichmentStatusLabel, signalKindLabel, usageSummaryText } from '../components/signalLabels';
import type { BehaviorSignalDetail, EnrichmentAvailability, EnrichmentJob, HandleSignalPayload } from '../api/types';

interface Props {
  signalId: string;
  loadSignalDetail: (signalId: string) => Promise<BehaviorSignalDetail>;
  loadEnrichmentAvailability: (signalId: string) => Promise<EnrichmentAvailability>;
  markRead: (signalId: string) => Promise<BehaviorSignalDetail>;
  handleSignal: (signalId: string, payload: HandleSignalPayload) => Promise<BehaviorSignalDetail>;
  requestEnrichment: (signalId: string, capabilityId: string) => Promise<EnrichmentJob>;
  cancelEnrichment: (jobId: string) => Promise<EnrichmentJob>;
  onBack: () => void;
  onOpenFact?: (factId: string) => void;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; signal: BehaviorSignalDetail; enrichmentAvailability: EnrichmentAvailability };

export function SignalDetailPage({
  signalId,
  loadSignalDetail,
  loadEnrichmentAvailability,
  markRead,
  handleSignal,
  requestEnrichment,
  cancelEnrichment,
  onBack,
  onOpenFact
}: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [dialogOpen, setDialogOpen] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [signal, enrichmentAvailability] = await Promise.all([
      loadSignalDetail(signalId),
      loadEnrichmentAvailability(signalId)
    ]);
    setState({ status: 'ready', signal, enrichmentAvailability });
  }, [loadEnrichmentAvailability, loadSignalDetail, signalId]);

  useEffect(() => {
    let cancelled = false;
    reload().catch(() => {
      if (!cancelled) setState({ status: 'error' });
    });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  if (state.status === 'loading') return <section className="panel">正在加载信号详情</section>;
  if (state.status === 'error') {
    return (
      <section className="panel">
        <p>信号详情不可用。</p>
        <button onClick={onBack}>返回总览</button>
      </section>
    );
  }

  const { enrichmentAvailability, signal } = state;
  return (
    <section className="panel signal-detail" aria-label="信号详情" data-testid="signal-detail">
      <header className="detail-header detail-header--sticky">
        <div>
          <h2>{signal.title}</h2>
          <p>{signalKindLabel(signal.signal_kind)} / {signal.severity} / {signal.confidence}</p>
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
        <button data-testid="mark-signal-read" disabled={signal.decision_state !== 'unread'} onClick={() => runMutation(() => markRead(signal.signal_id))}>
          标记已读
        </button>
        <button className="primary" data-testid="handle-signal" onClick={() => setDialogOpen(true)}>
          处理信号
        </button>
      </div>
      {mutationError && <p role="alert">{mutationError}</p>}
      {dialogOpen && (
        <HandleSignalDialog
          onCancel={() => setDialogOpen(false)}
          onSubmit={async (payload) => {
            await runMutation(() => handleSignal(signal.signal_id, payload));
            setDialogOpen(false);
          }}
        />
      )}

      <div className="detail-summary detail-summary--wide" aria-label="信号摘要">
        <div>
          <span>为什么重要</span>
          <strong>{signal.why_it_matters}</strong>
        </div>
        <div>
          <span>状态</span>
          <strong>
            {decisionStateLabel(signal.decision_state)}
            {signal.conclusion_code ? `，${conclusionCodeLabel(signal.conclusion_code)}` : ''}
          </strong>
          {signal.note && <small>{signal.note}</small>}
        </div>
        <div>
          <span>用量</span>
          <strong>{usageSummaryText(signal.usage_summary)}</strong>
        </div>
        <div>
          <span>补证</span>
          <strong>
            {enrichmentStatusLabel(signal.enrichment_status_summary.status)}
            {signal.enrichment_status_summary.reason_code ? `，${signal.enrichment_status_summary.reason_code}` : ''}
          </strong>
        </div>
      </div>

      <section>
        <h3>建议动作</h3>
        <ul className="plain-list">
          {signal.suggested_actions.map((action) => <li key={action}>{action}</li>)}
        </ul>
      </section>

      <EnrichmentPanel
        signalId={signal.signal_id}
        availability={enrichmentAvailability}
        requestEnrichment={requestEnrichment}
        cancelEnrichment={cancelEnrichment}
        onChanged={reload}
      />

      <section aria-label="关联会话">
        <h3>关联会话</h3>
        <div className="row-list">
          {signal.linked_conversations.length === 0 ? (
            <p>暂无可定位会话。</p>
          ) : signal.linked_conversations.map((item) => (
            <div className="collector-row" key={item.conversation_ref}>
              <div className="collector-row__identity">
                <strong>{item.conversation_ref}</strong>
                <small>{item.hit_count} 条命中 / {item.last_seen_at ?? '未知时间'}</small>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section aria-label="证据分组" data-testid="evidence-groups">
        <h3>证据分组</h3>
        <div className="signal-group-list">
          {signal.evidence_groups.map((group) => (
            <article className="signal-group" key={group.group_id}>
              <header>
                <strong>{group.title}</strong>
                <span className="badge gray">{group.count} 条</span>
              </header>
              <p>{group.summary}</p>
              <ul>
                {group.items.map((item) => (
                  <li key={item.evidence_ref}>
                    <span>{item.occurred_at ?? '无时间'}</span>
                    <strong>{item.summary}</strong>
                    <small>{item.content_preview}</small>
                    {item.fact_id && (
                      <button className="compact-button" onClick={() => onOpenFact?.(item.fact_id!)} type="button">
                        查看会话
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>
    </section>
  );

  async function runMutation(action: () => Promise<BehaviorSignalDetail>) {
    setMutationError(null);
    try {
      setState({ status: 'ready', signal: await action(), enrichmentAvailability });
    } catch {
      setMutationError('信号操作失败。请刷新后重试。');
    }
  }
}
