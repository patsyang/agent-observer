import { ArrowRight } from 'lucide-react';

import type { BehaviorSignal } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { decisionStateLabel, enrichmentStatusLabel, scopeText, signalKindLabel } from './signalLabels';
import { primaryToolContext } from './ToolContextBlock';

interface Props {
  signal: BehaviorSignal;
  onOpen: (signalId: string) => void;
}

export function SignalCard({ signal, onOpen }: Props) {
  const toolContext = primaryToolContext(signal.evidence_groups.flatMap((group) => group.items));
  const conversation = signal.linked_conversations[0];
  return (
    <article className="signal-card" data-testid="signal-card" data-signal-key={signal.signal_key}>
      <div className="signal-card__header">
        <div>
          <div className="signal-card__badges">
            <span className="badge violet">{signalKindLabel(signal.signal_kind)}</span>
            <span className="badge teal">{signal.workspace_summary?.label ?? '工作区未知'}</span>
            <span className="badge gray">{signal.severity} / {signal.confidence}</span>
            <span className="badge teal">最近 {formatSignalTime(signal.last_event_at)}</span>
          </div>
          <h3>{signal.title}</h3>
          <small>{signal.why_it_matters}</small>
        </div>
      </div>

      <div className="signal-card__meta" data-testid="signal-card-meta">
        <div>
          <span>会话</span>
          <strong>{conversation?.session_title || conversation?.session_ref || conversation?.conversation_ref || '未知会话'}</strong>
        </div>
        <div>
          <span>命中</span>
          <strong>{formatNumber(signal.occurrence_count ?? 0)} 次</strong>
        </div>
        <div>
          <span>状态</span>
          <strong>{decisionStateLabel(signal.decision_state)}</strong>
        </div>
        <div>
          <span>影响范围</span>
          <strong>{scopeText(signal.affected_scope)}</strong>
        </div>
      </div>

      <div className="signal-card__context" data-testid="signal-card-context">
        <section>
          <span>最近命令</span>
          <p>{toolContext?.command_excerpt || toolContext?.command || signal.latest_summary || '暂无命令上下文'}</p>
        </section>
        <section>
          <span>错误摘要</span>
          <p>{toolContext?.error_excerpt || enrichmentStatusLabel(signal.enrichment_status_summary.status)}</p>
        </section>
      </div>

      <div className="signal-card__footer">
        <button className="compact-button primary" data-testid="open-signal" onClick={() => onOpen(signal.signal_id)}>
          查看信号
          <ArrowRight aria-hidden="true" size={15} />
        </button>
      </div>
    </article>
  );
}

function formatSignalTime(value?: string | null): string {
  if (!value) return '暂无时间';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
}
