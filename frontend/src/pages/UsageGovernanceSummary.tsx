import type { RiskSummary, UsageSummary } from '../api/types';
import { Metric } from '../components/Metric';
import { formatNumber } from '../utils/numberFormat';
import {
  activityTagLabel,
  objectTypeLabel,
  riskTypeLabel,
  scopeValueLabel,
  severityLabel,
} from './dashboardLabels';

interface Props {
  usage: UsageSummary;
  risks: RiskSummary;
  compact?: boolean;
  pendingSignalCount?: number;
}

export function UsageGovernanceSummary({ usage, risks, compact = false, pendingSignalCount }: Props) {
  const session = usage.rollups.find((row) => row.scope === 'session' && row.scope_value !== 'unknown');
  const conversation = usage.rollups.find((row) => row.scope === 'conversation' && row.scope_value !== 'unknown');
  const activityRows = usage.rollups.filter((row) => row.scope === 'activity_tag');
  const riskCount = pendingSignalCount ?? risks.signals.reduce((total, signal) => total + signal.count, 0);

  return (
    <section className={compact ? 'panel flush summary-band summary-band--compact' : 'panel flush summary-band'} aria-label="使用与风险治理" data-testid="usage-governance">
      <div className="panel-header">
        <h2>使用与风险治理</h2>
        <span className="badge gray">确定性汇总</span>
      </div>
      <div className="panel-body">
        {compact ? (
          <div className="metric-grid">
            <CompactMetric label="有效用量 (Token)" value={formatNumber(usage.totals.effective_units)} />
            <CompactMetric label={`缓存命中 (${formatPercent(usage.totals.cache_hit_rate)})`} value={formatNumber(usage.totals.cached_input_units)} />
            <CompactMetric label="待处理信号" value={formatNumber(riskCount)} />
          </div>
        ) : (
          <div className="metric-grid">
            <Metric label="有效用量" value={formatNumber(usage.totals.effective_units)} note="模型调用有效 token" />
            <Metric label="缓存命中" value={formatNumber(usage.totals.cached_input_units)} note={`命中率 ${formatPercent(usage.totals.cache_hit_rate)}`} />
            <Metric label="待处理信号" value={formatNumber(riskCount)} note="当前时间范围内未处理" />
          </div>
        )}
        {!compact && <div className="summary-columns">
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
                <p data-testid={`usage-rollup-${row.activity_tag}`} key={row.rollup_id}>
                  {activityTagLabel(row.activity_tag)}：{formatNumber(row.units)}
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
                <p data-testid={`risk-signal-${signal.risk_type}-${signal.object_type}`} key={`${signal.risk_type}-${signal.object_type}`}>
                  {riskTypeLabel(signal.risk_type)} / {objectTypeLabel(signal.object_type)}：
                  {formatNumber(signal.count)}，{severityLabel(signal.highest_severity)}
                </p>
              ))
            )}
          </section>
        </div>}
      </div>
    </section>
  );
}

function CompactMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric metric--compact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function sumScope(usage: UsageSummary, scope: string, scopeValue?: string): number {
  if (!scopeValue) return 0;
  return usage.rollups
    .filter((row) => row.scope === scope && row.scope_value === scopeValue)
    .reduce((total, row) => total + row.units, 0);
}

function formatPercent(value?: number): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}
