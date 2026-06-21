import type { UsageSummary } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { formatDateTime } from './dashboardLabels';

export function UsageTrendChart({ usage }: { usage: UsageSummary }) {
  const points = usage.trend ?? [];
  const pointValues = points.map((point) => point.effective_units);
  const cachedValues = points.map((point) => point.cached_input_units);
  const max = Math.max(1, ...pointValues, ...cachedValues);
  const total = usage.totals.effective_units;
  const cachedTotal = usage.totals.cached_input_units;
  const effectivePeak = Math.max(...pointValues);
  const peakIndex = pointValues.indexOf(effectivePeak);
  const peakPoint = points[peakIndex];
  const width = Math.max(560, Math.max(1, points.length) * 96);
  const height = 190;
  const plotTop = 32;
  const plotHeight = 116;
  const xStart = 24;
  const xEnd = width - 24;
  const linePath = (values: number[]) => points
    .map((_point, index) => {
      const x = points.length <= 1 ? width / 2 : xStart + (index / (points.length - 1)) * (xEnd - xStart);
      const value = values[index];
      const y = plotTop + plotHeight - (value / max) * plotHeight;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
  const tokenPath = linePath(pointValues);
  const cachedPath = linePath(cachedValues);

  return (
    <section className="panel flush usage-trend" aria-label="用量趋势">
      <div className="panel-header">
        <h2>用量趋势</h2>
        <span className="badge teal">{formatNumber(total)} token / 缓存 {formatNumber(cachedTotal)}</span>
      </div>
      <div className="panel-body">
        {points.length === 0 ? (
          <p>当前时间范围暂无用量数据。</p>
        ) : (
          <>
            <p className="usage-trend-note">
              每个点表示该时间桶内 token 合计，不是瞬时消耗；{bucketLabel(usage.window)}；缓存命中率 {formatPercent(usage.totals.cache_hit_rate)}。
            </p>
            <div className="usage-trend-legend" aria-label="用量趋势图例">
              <span><i className="usage-trend-swatch token" />有效 token</span>
              <span><i className="usage-trend-swatch cache" />缓存命中 token</span>
            </div>
            <div className="usage-trend-scroll">
              <svg
                className="usage-trend-chart"
                height={height}
                viewBox={`0 0 ${width} ${height}`}
                width={width}
                role="img"
                aria-label="选择时间范围内 token 用量与缓存命中折线图"
              >
                <path className="usage-trend-grid" d={`M ${xStart} ${plotTop + plotHeight} H ${xEnd}`} />
                <path className="usage-trend-line" d={tokenPath} />
                <path className="usage-trend-line cache" d={cachedPath} />
                {points.map((point, index) => {
                  const x = points.length <= 1 ? width / 2 : xStart + (index / (points.length - 1)) * (xEnd - xStart);
                  const value = pointValues[index];
                  const y = plotTop + plotHeight - (value / max) * plotHeight;
                  const cached = cachedValues[index];
                  const cachedY = plotTop + plotHeight - (cached / max) * plotHeight;
                  return (
                    <g key={point.bucket}>
                      <text className="usage-trend-value" x={x} y={Math.max(12, y - 10)} textAnchor="middle">
                        {formatNumber(value)}
                      </text>
                      <circle className="usage-trend-dot" cx={x} cy={y} r="3.5" />
                      <text className="usage-trend-value cache" x={x} y={Math.min(height - 8, cachedY + 16)} textAnchor="middle">
                        {formatNumber(cached)}
                      </text>
                      <circle className="usage-trend-dot cache" cx={x} cy={cachedY} r="3.5" />
                    </g>
                  );
                })}
              </svg>
            </div>
            <div className="usage-trend-footer">
              <span>{formatDateTime(points[0]?.bucket)}</span>
              <strong>有效峰值 {formatNumber(effectivePeak)}{peakPoint ? ` · ${formatDateTime(peakPoint.bucket)}` : ''}</strong>
              <span>缓存命中 {formatNumber(cachedTotal)} / {formatPercent(usage.totals.cache_hit_rate)}</span>
              <span>{formatDateTime(points[points.length - 1]?.bucket)}</span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function bucketLabel(window: string): string {
  if (window === '1h') return '按约 5 分钟聚合';
  if (window === '24h') return '按小时聚合';
  if (window === '7d') return '按天聚合';
  return '按可用数据时间桶聚合';
}

function formatPercent(value?: number): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}
