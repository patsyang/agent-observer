import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { ConversationDrawer } from './ConversationDrawer';
import { EnrichmentPanel } from '../components/EnrichmentPanel';
import { HandleSignalDialog } from '../components/HandleSignalDialog';
import { SensitiveEvidence } from '../components/SensitiveEvidence';
import { signalKindLabel } from '../components/signalLabels';
import type {
  BehaviorSignalDetail,
  ConversationDetail,
  ConversationHitsResponse,
  ConversationMessagesResponse,
  EnrichmentAvailability,
  EnrichmentJob,
  HandleSignalPayload,
  HitsByFactIdsResponse,
  LinkedConversation,
  MessageLocateResponse,
} from '../api/types';
import { SignalDetailSummary } from './SignalDetailSummary';
import { SignalLinkedConversations } from './SignalLinkedConversations';
import { SignalWorkspaceChips } from './SignalWorkspaceChips';
import { ToolContextBlock } from '../components/ToolContextBlock';
import { formatFullDateTime } from './dashboardLabels';
import type { SignalEvidenceItem } from '../api/types';

interface Props {
  signalId: string;
  loadSignalDetail: (signalId: string) => Promise<BehaviorSignalDetail>;
  loadConversationDetail: (conversationRef: string) => Promise<ConversationDetail>;
  loadConversationForFact: (factId: string) => Promise<ConversationDetail>;
  loadConversationMessages: (ref: string, role?: string, page?: number) => Promise<ConversationMessagesResponse>;
  loadConversationHits: (ref: string, category?: string, page?: number) => Promise<ConversationHitsResponse>;
  locateConversationMessage: (ref: string, factId: string) => Promise<MessageLocateResponse>;
  loadConversationHitsByFactIds: (ref: string, factIds: string[]) => Promise<HitsByFactIdsResponse>;
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
  loadConversationDetail,
  loadConversationForFact,
  loadConversationMessages,
  loadConversationHits,
  locateConversationMessage,
  loadConversationHitsByFactIds,
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
  const [drawer, setDrawer] = useState<{ detail: ConversationDetail; hitIds: string[] } | null>(null);
  const [drawerError, setDrawerError] = useState<string | null>(null);

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
  const eventGroups = signal.evidence_groups.filter((group) => group.group_type !== 'conversation');
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

      <SignalDetailSummary signal={signal} />

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

      <SignalWorkspaceChips workspaces={signal.workspace_refs ?? []} />
      <SignalLinkedConversations conversations={signal.linked_conversations} onOpen={openLinkedConversation} />
      {drawerError && <p role="alert">{drawerError}</p>}

      <section aria-label="命中事件" data-testid="evidence-groups">
        <h3>命中事件</h3>
        <div className="signal-group-list">
          {eventGroups.map((group) => (
            <article className="signal-group" key={group.group_id}>
              <header>
                <strong>{group.title}</strong>
                <span className="badge gray">{group.count} 条</span>
              </header>
              <p>{group.summary}</p>
              <ul>
                {group.items.map((item) => (
                  <li key={item.evidence_ref}>
                    <span>{formatFullDateTime(item.occurred_at)}</span>
                    <div className="signal-event-main">
                      <strong>{item.summary}</strong>
                      <small>{item.content_preview}</small>
                      <SensitiveEvidence matches={item.sensitive_matches} />
                      <ToolContextBlock context={item.tool_context} compact />
                    </div>
                    {item.fact_id && (
                      <button className="compact-button" onClick={() => openEvidenceConversation(item)} type="button">
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
      {drawer && (
        <ConversationDrawer
          detail={drawer.detail}
          highlightFactIds={drawer.hitIds}
          highlightTitle="当前信号命中"
          onClose={() => setDrawer(null)}
          loadMessages={loadConversationMessages}
          loadHits={loadConversationHits}
          locateMessage={locateConversationMessage}
          loadHitsByFactIds={loadConversationHitsByFactIds}
        />
      )}
    </section>
  );

  async function openLinkedConversation(conversation: LinkedConversation) {
    setDrawerError(null);
    try {
      const detail = await loadConversationDetail(conversation.conversation_ref);
      setDrawer({ detail, hitIds: conversation.matched_fact_ids ?? [] });
    } catch {
      setDrawerError('会话详情加载失败。请稍后重试。');
    }
  }

  async function openEvidenceConversation(item: SignalEvidenceItem) {
    if (!item.conversation_ref) {
      if (item.fact_id) onOpenFact?.(item.fact_id);
      return;
    }
    setDrawerError(null);
    try {
      // 优先用 loadConversationForFact 携带 focus_fact_id，drawer 内自动定位目标页
      const detail = item.fact_id
        ? await loadConversationForFact(item.fact_id)
        : await loadConversationDetail(item.conversation_ref);
      setDrawer({ detail, hitIds: item.fact_id ? [item.fact_id] : [] });
    } catch {
      setDrawerError('会话详情加载失败。请稍后重试。');
    }
  }

  async function runMutation(action: () => Promise<BehaviorSignalDetail>) {
    setMutationError(null);
    try {
      setState({ status: 'ready', signal: await action(), enrichmentAvailability });
    } catch {
      setMutationError('信号操作失败。请刷新后重试。');
    }
  }
}
