import type { FactQuality, FactsResponse, RiskSummary, TimeWindow, UsageSummary } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { objectTypeLabel, riskTypeLabel, severityLabel } from './dashboardLabels';

export type FactJumpFilters = {
  quality?: FactQuality | 'all';
  fact_type?: string;
  source?: string;
  window?: TimeWindow;
  include_health?: boolean;
};

interface Props {
  facts: FactsResponse;
  risks: RiskSummary;
  usage: UsageSummary;
  window: TimeWindow;
  onOpenFacts?: (filters: FactJumpFilters) => void;
}

export function DashboardInvestigationSummary({ facts, onOpenFacts, risks, usage, window }: Props) {
  const topRisk = risks.signals[0];
  const lowFacts = facts.facts.filter((fact) => fact.quality === 'low').length;
  const rawFacts = facts.facts.filter((fact) => fact.raw_available).length;
  const totalFacts = facts.total ?? facts.facts.length;
  const unknownUsage = usage.totals.unknown_units;

  return (
    <section className="panel flush investigation-panel" aria-label="排查摘要">
      <div className="panel-header">
        <h2>排查摘要</h2>
        <span className="badge teal">可下钻</span>
      </div>
      <p className="panel-intro">只放能帮助定位问题的入口：风险、用量、待补证和原文可用性。</p>
      <div className="panel-body investigation-list">
        <InvestigationItem
          action="筛选风险"
          meta={topRisk ? `${severityLabel(topRisk.highest_severity)} · 最近 ${topRisk.last_seen_at ? formatShortDate(topRisk.last_seen_at) : '未知'}` : '当前时间窗无风险'}
          onClick={() => onOpenFacts?.({ fact_type: 'risk', window })}
          title="风险 Top 项"
          value={topRisk ? `${riskTypeLabel(topRisk.risk_type)} / ${objectTypeLabel(topRisk.object_type)}：${formatNumber(topRisk.count)}` : '暂无风险信号'}
        />
        <InvestigationItem
          action="查看用量"
          meta={unknownUsage > 0 ? '存在未识别活动，需要结合事实判断' : '暂无明显异常'}
          onClick={() => onOpenFacts?.({ fact_type: 'usage', window })}
          title="用量异常"
          value={unknownUsage > 0 ? `未知活动 ${formatNumber(unknownUsage)}` : `关联 ${formatNumber(usage.totals.associated_units)} / 归因 ${formatNumber(usage.totals.attributed_units)}`}
        />
        <InvestigationItem
          action="查看待补证"
          meta={lowFacts > 0 ? '需要补上下文或确认证据质量' : '当前无待补证事实'}
          onClick={() => onOpenFacts?.({ quality: 'low', window })}
          title="待补证"
          value={`${formatNumber(lowFacts)} 条`}
        />
        <InvestigationItem
          action="查看事实"
          meta={rawFacts > 0 ? '可直接打开原文排查' : '当前事实只有摘要和字段'}
          onClick={() => onOpenFacts?.({ window })}
          title="原文可用情况"
          value={`${formatNumber(rawFacts)} / ${formatNumber(totalFacts)} 条已上传原文`}
        />
      </div>
    </section>
  );
}

function InvestigationItem({
  action,
  meta,
  onClick,
  title,
  value
}: {
  action: string;
  meta: string;
  onClick: () => void;
  title: string;
  value: string;
}) {
  return (
    <div className="investigation-item">
      <div>
        <span>{title}</span>
        <strong>{value}</strong>
        <small>{meta}</small>
      </div>
      <button className="compact-button" onClick={onClick} type="button">
        {action}
      </button>
    </div>
  );
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
