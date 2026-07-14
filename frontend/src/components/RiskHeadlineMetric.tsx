import type { SignalSummary } from '../api/types';

interface Props {
  summary: SignalSummary | null;
  loading: boolean;
  activeFamily: string | null;
  onSelectFamily: (family: string | null) => void;
}

/**
 * 使命头条：显示待研判风险总数（= 下方列表同源同窗），按 severity 与 risk_family 拆解。
 * family 片段可点 → 过滤下方“行为风险信号”列表；数字永远与列表一致。
 */
export function RiskHeadlineMetric({ summary, loading, activeFamily, onSelectFamily }: Props) {
  const families = summary?.families ?? [];
  const severityTotals = families.reduce(
    (acc, family) => {
      acc.high += family.by_severity.high ?? 0;
      acc.medium += family.by_severity.medium ?? 0;
      acc.low += family.by_severity.low ?? 0;
      return acc;
    },
    { high: 0, medium: 0, low: 0 }
  );
  const total = summary?.total ?? 0;

  return (
    <div className="metric risk-headline" aria-label="待研判风险" data-testid="risk-headline">
      <span>待研判风险</span>
      <strong>{loading ? <span className="loading-inline">加载中</span> : total}</strong>
      <small className="risk-severity-note">
        {loading ? <span className="loading-inline">加载中</span> : `高危 ${severityTotals.high} · 中危 ${severityTotals.medium} · 低危 ${severityTotals.low}`}
      </small>
      {loading ? null : (
        <div className="risk-family-segments" role="group" aria-label="按风险分类筛选">
          <button
            type="button"
            className={`chip ${activeFamily === null ? 'active' : ''}`}
            onClick={() => onSelectFamily(null)}
          >
            全部 {total}
          </button>
          {families.map((family) => (
            <button
              key={family.id}
              type="button"
              className={[
                'chip',
                activeFamily === family.id ? 'active' : '',
                family.id === 'uncategorized' ? 'chip-warn' : ''
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => onSelectFamily(activeFamily === family.id ? null : family.id)}
              disabled={family.total === 0}
              title={family.label}
            >
              {family.label} {family.total}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
