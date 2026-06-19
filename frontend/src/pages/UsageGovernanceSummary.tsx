import type { RiskSummary, UsageSummary } from '../api/types';
import { Metric } from '../components/Metric';
import { formatNumber } from '../utils/numberFormat';
import {
  activityTagLabel,
  objectTypeLabel,
  riskTypeLabel,
  scopeValueLabel,
  severityLabel,
  usageKindLabel,
} from './dashboardLabels';

interface Props {
  usage: UsageSummary;
  risks: RiskSummary;
}

export function UsageGovernanceSummary({ usage, risks }: Props) {
  const session = usage.rollups.find((row) => row.scope === 'session' && row.scope_value !== 'unknown');
  const conversation = usage.rollups.find((row) => row.scope === 'conversation' && row.scope_value !== 'unknown');
  const activityRows = usage.rollups.filter((row) => row.scope === 'activity_tag');

  return (
    <section className="panel flush summary-band" aria-label="使用与风险治理">
      <div className="panel-header">
        <h2>使用与风险治理</h2>
        <span className="badge gray">确定性汇总</span>
      </div>
      <div className="panel-body">
        <div className="metric-grid">
          <Metric label="关联用量" value={formatNumber(usage.totals.associated_units)} note="不可简单相加" />
          <Metric label="归因用量" value={formatNumber(usage.totals.attributed_units)} note="仅确定性证据" />
          <Metric label="未知活动" value={formatNumber(usage.totals.unknown_units)} note="不由 AI 猜测" />
        </div>
        <div className="summary-columns">
          <section>
            <h3>范围</h3>
            <p>
              Session：{session ? `${scopeValueLabel('session', session.scope_value)} / ${formatNumber(sumScope(usage, 'session', session.scope_value))}` : '暂无'}
            </p>
            <p>
              Conversation：
              {conversation ? `${scopeValueLabel('conversation', conversation.scope_value)} / ${formatNumber(sumScope(usage, 'conversation', conversation.scope_value))}` : '暂无'}
            </p>
          </section>
          <section>
            <h3>活动标签</h3>
            {activityRows.length === 0 ? (
              <p>暂无活动用量。</p>
            ) : (
              activityRows.map((row) => (
                <p key={row.rollup_id}>
                  {activityTagLabel(row.activity_tag)}：{formatNumber(row.units)}，{usageKindLabel(row.usage_kind)}
                </p>
              ))
            )}
          </section>
          <section>
            <h3>风险信号</h3>
            {risks.signals.length === 0 ? (
              <p>暂无高风险或敏感对象信号。</p>
            ) : (
              risks.signals.map((signal) => (
                <p key={`${signal.risk_type}-${signal.object_type}`}>
                  {riskTypeLabel(signal.risk_type)} / {objectTypeLabel(signal.object_type)}：
                  {formatNumber(signal.count)}，{severityLabel(signal.highest_severity)}
                </p>
              ))
            )}
          </section>
        </div>
      </div>
    </section>
  );
}

function sumScope(usage: UsageSummary, scope: string, scopeValue?: string): number {
  if (!scopeValue) return 0;
  return usage.rollups
    .filter((row) => row.scope === scope && row.scope_value === scopeValue)
    .reduce((total, row) => total + row.units, 0);
}
