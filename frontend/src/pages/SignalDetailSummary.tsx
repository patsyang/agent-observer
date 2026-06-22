import type { BehaviorSignal } from '../api/types';
import { conclusionCodeLabel, decisionStateLabel, enrichmentStatusLabel, usageSummaryText } from '../components/signalLabels';
import { formatNumber } from '../utils/numberFormat';

interface Props {
  signal: BehaviorSignal;
}

export function SignalDetailSummary({ signal }: Props) {
  return (
    <div className="signal-insight-grid" aria-label="信号判断摘要">
      <div className="signal-insight-card signal-insight-card--wide">
        <span>判断依据</span>
        <strong>{signal.why_it_matters}</strong>
      </div>
      <div className="signal-insight-card">
        <span>影响范围</span>
        <strong>{impactSummary(signal)}</strong>
      </div>
      <div className="signal-insight-card">
        <span>处置状态</span>
        <strong>{decisionStateLabel(signal.decision_state)}</strong>
        {signal.conclusion_code && <small>{conclusionCodeLabel(signal.conclusion_code)}</small>}
      </div>
      <div className="signal-insight-card">
        <span>本机补证</span>
        <strong>{enrichmentStatusLabel(signal.enrichment_status_summary.status)}</strong>
        {signal.enrichment_status_summary.reason_code && <small>{signal.enrichment_status_summary.reason_code}</small>}
      </div>
      <div className="signal-insight-card">
        <span>用量</span>
        <strong>{usageSummaryText(signal.usage_summary)}</strong>
      </div>
    </div>
  );
}

function impactSummary(signal: BehaviorSignal): string {
  const scope = signal.affected_scope;
  const conversations = numberValue(scope.conversation_count) || signal.linked_conversations.length;
  const hits = numberValue(scope.failure_count) || numberValue(scope.operation_count) || signal.occurrence_count || 0;
  const workspaces = signal.workspace_summary?.count ?? signal.workspace_refs.length;
  return `${formatNumber(conversations)} 会话 / ${formatNumber(hits)} 命中 / ${formatNumber(workspaces)} 工作区`;
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}
