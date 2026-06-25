import { useEffect, useRef, useState } from 'react';

import type { UsageSummary } from '../api/types';
import { formatNumber } from '../utils/numberFormat';

export function UsageTrendChart({ usage }: { usage: UsageSummary }) {
  const chartHostRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const points = usage.trend ?? [];
  const pointValues = points.map((point) => point.effective_units);
  const cachedValues = points.map((point) => point.cached_input_units);
  const max = Math.max(1, ...pointValues, ...cachedValues);
  const totalInput = usage.totals.input_token_units;
  const totalOutput = usage.totals.output_token_units;
  const effectiveTotal = usage.totals.effective_units;
  const cachedTotal = usage.totals.cached_input_units;
  const cacheObservedInput = usage.totals.cache_observed_input_units;
  const creditTotal = usage.totals.credit_total;
  const bucketMinutes = usage.bucket_size_minutes;
  const effectivePeak = Math.max(...pointValues);
  const peakIndex = pointValues.indexOf(effectivePeak);
  const peakPoint = points[peakIndex];
  const axisTicks = boundaryTicks(points.map((point) => point.bucket), bucketMinutes);
  const minWidth = Math.max(560, Math.max(1, points.length) * 96);
  const width = Math.max(minWidth, containerWidth);
  const height = 154;
  const valueLabelTop = 15;
  const valueLabelGap = 14;
  const plotTop = 50;
  const plotHeight = 56;
  const xStart = 24;
  const xEnd = width - 24;
  const groupWidth = points.length <= 1 ? xEnd - xStart : (xEnd - xStart) / points.length;
  const barWidth = Math.max(8, Math.min(18, groupWidth * 0.18));
  const valueLabelRightOffset = Math.min(44, groupWidth * 0.42);

  useEffect(() => {
    const node = chartHostRef.current;
    if (!node) return undefined;
    const updateWidth = () => setContainerWidth(Math.floor(node.clientWidth));
    updateWidth();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(updateWidth);
    observer.observe(node);
    return () => observer.disconnect();
  }, [points.length]);

  return (
    <section className="panel flush usage-trend" aria-label="用量趋势" data-testid="usage-trend">
      <div className="panel-header">
        <h2>用量趋势</h2>
        <div className="usage-trend-header-meta">
          <div className="usage-trend-legend" aria-label="用量趋势图例">
            <span><i className="usage-trend-swatch token" />实际计算 token</span>
            <span><i className="usage-trend-swatch cache" />缓存命中 token</span>
          </div>
          <span className="badge teal">
            总输入Token {formatNumber(totalInput)} / 输出Token {formatNumber(totalOutput)} / 实际计算Token {formatNumber(effectiveTotal)} / 缓存 {formatNumber(cachedTotal)}（{formatPercent(usage.totals.cache_hit_rate)}） / Credits {formatNumber(creditTotal)}
          </span>
        </div>
      </div>
      <div className="panel-body">
        {points.length === 0 ? (
          <p>当前时间范围暂无用量数据。</p>
        ) : (
          <>
            <div className="usage-trend-note-row">
              <p className="usage-trend-note">
                每根柱表示相邻两个刻度之间的 token 合计，包含左侧刻度，不包含右侧刻度；{bucketLabel(bucketMinutes)}。
                {cacheObservedInput < totalInput ? ` 缓存率覆盖输入Token ${formatNumber(cacheObservedInput)}。` : ''}
              </p>
              <span className="usage-trend-peak">
                实际计算Token最高 · 时间段：{formatNumber(effectivePeak)}{peakPoint ? ` · ${bucketRangeLabel(peakPoint.bucket, bucketMinutes)}` : ''}
              </span>
            </div>
            <div className="usage-trend-scroll" ref={chartHostRef}>
              <svg
                className="usage-trend-chart"
                height={height}
                viewBox={`0 0 ${width} ${height}`}
                width={width}
                role="img"
                aria-label="选择时间范围内实际计算 token 与缓存命中 token 柱状图"
              >
                <path className="usage-trend-grid" d={`M ${xStart} ${plotTop + plotHeight} H ${xEnd}`} />
                {points.map((point, index) => {
                  const x = points.length <= 1 ? width / 2 : xStart + groupWidth * index + groupWidth / 2;
                  const value = pointValues[index];
                  const y = plotTop + plotHeight - (value / max) * plotHeight;
                  const cached = cachedValues[index];
                  const cachedY = plotTop + plotHeight - (cached / max) * plotHeight;
                  const baseline = plotTop + plotHeight;
                  const valueLabelX = x + valueLabelRightOffset;
                  return (
                    <g key={point.bucket}>
                      <title>{bucketRangeLabel(point.bucket, bucketMinutes)}：实际计算Token {formatNumber(value)}，缓存命中 {formatNumber(cached)}</title>
                      <text className="usage-trend-value" x={valueLabelX} y={valueLabelTop} textAnchor="end">
                        {formatNumber(value)}
                      </text>
                      <text className="usage-trend-value cache" x={valueLabelX} y={valueLabelTop + valueLabelGap} textAnchor="end">
                        {formatNumber(cached)}
                      </text>
                      <rect className="usage-trend-bar" x={x - barWidth - 2} y={y} width={barWidth} height={Math.max(2, baseline - y)} rx="2" />
                      <rect className="usage-trend-bar cache" x={x + 2} y={cachedY} width={barWidth} height={Math.max(2, baseline - cachedY)} rx="2" />
                    </g>
                  );
                })}
                {axisTicks.map((tick, index) => {
                  const x = xStart + groupWidth * index;
                  return (
                    <g className="usage-trend-axis-tick" key={`${tick}-${index}`}>
                      <path d={`M ${x} ${plotTop + plotHeight} V ${plotTop + plotHeight + 5}`} />
                      <text className="usage-trend-axis-label" x={x} y={plotTop + plotHeight + 19} textAnchor="middle">
                        {tick}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function bucketLabel(minutes: number): string {
  if (minutes < 60) return `每根柱覆盖 ${minutes} 分钟`;
  if (minutes < 24 * 60) return `每根柱覆盖 ${minutes / 60} 小时`;
  if (minutes === 24 * 60) return '每根柱覆盖 1 天';
  return `每根柱覆盖 ${minutes / (24 * 60)} 天`;
}

function bucketRangeLabel(value: string, minutes: number): string {
  const start = new Date(value);
  if (Number.isNaN(start.getTime())) return value;
  const end = new Date(start.getTime() + bucketDurationMs(minutes));
  if (minutes < 24 * 60) return `[${formatMonthDay(start)} ${formatHourMinute(start)}, ${formatHourMinute(end)})`;
  return `[${formatMonthDay(start)}, ${formatMonthDay(end)})`;
}

function boundaryTicks(values: string[], minutes: number): string[] {
  if (values.length === 0) return [];
  const ticks = values.map((value) => boundaryTickLabel(value, minutes));
  const last = new Date(values[values.length - 1]);
  if (Number.isNaN(last.getTime())) return ticks;
  ticks.push(boundaryTickLabel(new Date(last.getTime() + bucketDurationMs(minutes)).toISOString(), minutes));
  return ticks;
}

function boundaryTickLabel(value: string, minutes: number): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  if (minutes < 24 * 60) return formatHourMinute(date);
  return formatMonthDay(date);
}

function bucketDurationMs(minutes: number): number {
  return minutes * 60 * 1000;
}

function formatMonthDay(value: Date): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
  }).format(value);
}

function formatHourMinute(value: Date): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(value);
}

function formatPercent(value?: number): string {
  return `${((value ?? 0) * 100).toFixed(1)}%`;
}
