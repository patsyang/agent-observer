import { ArrowRight } from 'lucide-react';

import type { BehaviorSignal } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { decisionStateLabel, enrichmentStatusLabel, scopeText, signalKindLabel } from './signalLabels';

interface Props {
  signal: BehaviorSignal;
  onOpen: (signalId: string) => void;
}

export function SignalCard({ signal, onOpen }: Props) {
  return (
    <article className="signal-card" data-testid="signal-card" data-signal-key={signal.signal_key}>
      <div className="signal-card__header">
        <div>
          <div className="signal-card__badges">
            <span className="badge violet">{signalKindLabel(signal.signal_kind)}</span>
            <span className="badge gray">{signal.severity} / {signal.confidence}</span>
            <span className="badge teal">最近 {formatSignalTime(signal.last_event_at)}</span>
          </div>
          <h3>{signal.title}</h3>
          <small>{signal.why_it_matters}</small>
        </div>
      </div>

      <dl className="signal-fields signal-fields--compact">
        <div>
          <dt>影响范围</dt>
          <dd>{scopeText(signal.affected_scope)}</dd>
        </div>
        <div>
          <dt>证据质量</dt>
          <dd>{formatNumber(signal.evidence_groups.length)} 组证据</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{decisionStateLabel(signal.decision_state)}</dd>
        </div>
        <div>
          <dt>命中</dt>
          <dd>{formatNumber(signal.occurrence_count ?? 0)} 次</dd>
        </div>
        <div>
          <dt>建议动作</dt>
          <dd>{signal.suggested_actions[0] ?? '查看证据分组'}</dd>
        </div>
        <div>
          <dt>补证</dt>
          <dd>{enrichmentStatusLabel(signal.enrichment_status_summary.status)}</dd>
        </div>
      </dl>

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

