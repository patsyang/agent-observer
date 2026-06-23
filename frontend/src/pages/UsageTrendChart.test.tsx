import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { UsageTrendChart } from './UsageTrendChart';

describe('UsageTrendChart', () => {
  it('uses readable bucket bars with axis labels and hover details', () => {
    const { container } = render(
      <UsageTrendChart
        usage={{
          window: '1h',
          bucket_size_minutes: 1,
          rollups: [],
          totals: {
            effective_units: 1_109_200,
            unknown_units: 0,
            cached_input_units: 950_000,
            input_token_units: 1_250_000,
            output_token_units: 109_200,
            total_token_units: 1_359_200,
            cache_write_input_units: 0,
            reasoning_output_units: 0,
            credit_total: 12.5,
            cache_observed_input_units: 1_250_000,
            cache_hit_rate: 0.76,
          },
          trend: [
            { bucket: '2026-06-21T08:00:00+08:00', effective_units: 120, unknown_units: 0, cached_input_units: 60, input_token_units: 200, output_token_units: 0, total_token_units: 200, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 200, cache_hit_rate: 0.3 },
            { bucket: '2026-06-21T08:05:00+08:00', effective_units: 1_109_150, unknown_units: 0, cached_input_units: 900_000, input_token_units: 1_000_000, output_token_units: 1_009_150, total_token_units: 2_009_150, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 12.5, cache_observed_input_units: 1_000_000, cache_hit_rate: 0.9 },
            { bucket: '2026-06-21T08:10:00+08:00', effective_units: 530, unknown_units: 0, cached_input_units: 49_940, input_token_units: 249_800, output_token_units: 0, total_token_units: 249_800, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 249_800, cache_hit_rate: 0.2 },
          ],
        }}
      />
    );

    expect(screen.getByText(/不是瞬时消耗/)).toBeInTheDocument();
    expect(screen.getByText(/每根柱覆盖 1 分钟/)).toBeInTheDocument();
    const legend = screen.getByLabelText('用量趋势图例');
    expect(legend).toContainElement(screen.getByText('缓存命中 token'));
    expect(legend).toContainElement(screen.getByText('有效 token'));
    expect(legend.closest('.panel-header')).not.toBeNull();
    expect(screen.getByText(/总输入Token 1,250,000 \/ 输出Token 109,200 \/ 有效Token 1,109,200 \/ 缓存 950,000（76.0%） \/ Credits 12.5/)).toBeInTheDocument();
    expect(screen.getByLabelText('选择时间范围内有效 token 与缓存命中 token 柱状图')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('60')).toBeInTheDocument();
    expect(screen.getByText('1,109,150')).toBeInTheDocument();
    expect(screen.getByText('900,000')).toBeInTheDocument();
    expect(screen.getByText('530')).toBeInTheDocument();
    expect(screen.getByText('49,940')).toBeInTheDocument();
    const valueLabels = Array.from(container.querySelectorAll('.usage-trend-value'));
    expect(valueLabels).toHaveLength(6);
    expect(valueLabels.every((label) => label.getAttribute('text-anchor') === 'end')).toBe(true);
    for (let index = 0; index < valueLabels.length; index += 2) {
      expect(valueLabels[index].getAttribute('x')).toBe(valueLabels[index + 1].getAttribute('x'));
    }
    expect(container.querySelectorAll('.usage-trend-axis-label')).toHaveLength(3);
    expect(screen.getByText('08:00')).toBeInTheDocument();
    expect(screen.getByText('08:05')).toBeInTheDocument();
    expect(screen.getByText('08:10')).toBeInTheDocument();
    expect(screen.getByText(/有效Token 120，缓存命中 60/)).toBeInTheDocument();
    expect(screen.getByText(/有效Token 530，缓存命中 49,940/)).toBeInTheDocument();
    expect(screen.getByText(/有效Token最高 · 时间段：1,109,150/)).toBeInTheDocument();
    expect(container.querySelector('.usage-trend-note-row')).toContainElement(screen.getByText(/有效Token最高 · 时间段：1,109,150/));
    expect(container.querySelector('.usage-trend-footer')).not.toBeInTheDocument();
    expect(screen.getAllByText(/08:05-08:05/).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/当前范围缓存命中合计/)).not.toBeInTheDocument();
    expect(screen.queryByText(/有效峰值/)).not.toBeInTheDocument();
  });

  it('expands sparse buckets to the available chart width', async () => {
    const originalClientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 960 });

    render(
      <UsageTrendChart
        usage={{
          window: '7d',
          bucket_size_minutes: 24 * 60,
          rollups: [],
          totals: {
            effective_units: 320,
            unknown_units: 0,
            cached_input_units: 480,
            input_token_units: 800,
            output_token_units: 0,
            total_token_units: 800,
            cache_write_input_units: 0,
            reasoning_output_units: 0,
            credit_total: 0,
            cache_observed_input_units: 800,
            cache_hit_rate: 0.6,
          },
          trend: [
            { bucket: '2026-06-21T00:00:00+08:00', effective_units: 320, unknown_units: 0, cached_input_units: 480, input_token_units: 800, output_token_units: 0, total_token_units: 800, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 800, cache_hit_rate: 0.6 },
          ],
        }}
      />
    );

    await waitFor(() => {
      expect(screen.getByLabelText('选择时间范围内有效 token 与缓存命中 token 柱状图')).toHaveAttribute('width', '960');
    });

    if (originalClientWidth) {
      Object.defineProperty(HTMLElement.prototype, 'clientWidth', originalClientWidth);
    } else {
      delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
    }
  });

  it('uses server bucket size for today hourly trend labels', () => {
    render(
      <UsageTrendChart
        usage={{
          window: 'today',
          bucket_size_minutes: 60,
          rollups: [],
          totals: {
            effective_units: 320,
            unknown_units: 0,
            cached_input_units: 80,
            input_token_units: 500,
            output_token_units: 0,
            total_token_units: 500,
            cache_write_input_units: 0,
            reasoning_output_units: 0,
            credit_total: 0,
            cache_observed_input_units: 500,
            cache_hit_rate: 0.16,
          },
          trend: [
            { bucket: '2026-06-21T08:00:00+08:00', effective_units: 120, unknown_units: 0, cached_input_units: 30, input_token_units: 200, output_token_units: 0, total_token_units: 200, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 200, cache_hit_rate: 0.15 },
            { bucket: '2026-06-21T09:00:00+08:00', effective_units: 200, unknown_units: 0, cached_input_units: 50, input_token_units: 300, output_token_units: 0, total_token_units: 300, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 300, cache_hit_rate: 0.1667 },
          ],
        }}
      />
    );

    expect(screen.getByText(/每根柱覆盖 1 小时/)).toBeInTheDocument();
    expect(screen.getByText('08:00')).toBeInTheDocument();
    expect(screen.getByText('09:00')).toBeInTheDocument();
    expect(screen.getAllByText(/08:00-08:59/).length).toBeGreaterThanOrEqual(1);
  });

  it('uses server bucket size for six-hour trend labels', () => {
    render(
      <UsageTrendChart
        usage={{
          window: '6h',
          bucket_size_minutes: 30,
          rollups: [],
          totals: {
            effective_units: 300,
            unknown_units: 0,
            cached_input_units: 20,
            input_token_units: 400,
            output_token_units: 0,
            total_token_units: 400,
            cache_write_input_units: 0,
            reasoning_output_units: 0,
            credit_total: 0,
            cache_observed_input_units: 400,
            cache_hit_rate: 0.05,
          },
          trend: [
            { bucket: '2026-06-23T13:30:00+08:00', effective_units: 100, unknown_units: 0, cached_input_units: 10, input_token_units: 200, output_token_units: 0, total_token_units: 200, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 200, cache_hit_rate: 0.05 },
            { bucket: '2026-06-23T14:00:00+08:00', effective_units: 200, unknown_units: 0, cached_input_units: 10, input_token_units: 200, output_token_units: 0, total_token_units: 200, cache_write_input_units: 0, reasoning_output_units: 0, credit_total: 0, cache_observed_input_units: 200, cache_hit_rate: 0.05 },
          ],
        }}
      />
    );

    expect(screen.getByText(/每根柱覆盖 30 分钟/)).toBeInTheDocument();
    expect(screen.getByText('13:30')).toBeInTheDocument();
    expect(screen.getByText('14:00')).toBeInTheDocument();
    expect(screen.getAllByText(/13:30-13:59/).length).toBeGreaterThanOrEqual(1);
  });

});
