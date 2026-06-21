import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { UsageTrendChart } from './UsageTrendChart';

describe('UsageTrendChart', () => {
  it('labels every bucket value and explains bucket aggregation', () => {
    render(
      <UsageTrendChart
        usage={{
          window: '1h',
          rollups: [],
          totals: {
            effective_units: 1_109_200,
            unknown_units: 0,
            cached_input_units: 950_000,
            input_token_units: 1_250_000,
            cache_hit_rate: 0.76,
          },
          trend: [
            { bucket: '2026-06-21T08:00:00+00:00', effective_units: 120, unknown_units: 0, cached_input_units: 60, input_token_units: 200, cache_hit_rate: 0.3 },
            { bucket: '2026-06-21T08:05:00+00:00', effective_units: 1_109_150, unknown_units: 0, cached_input_units: 900_000, input_token_units: 1_000_000, cache_hit_rate: 0.9 },
            { bucket: '2026-06-21T08:10:00+00:00', effective_units: 530, unknown_units: 0, cached_input_units: 49_940, input_token_units: 249_800, cache_hit_rate: 0.2 },
          ],
        }}
      />
    );

    expect(screen.getByText(/不是瞬时消耗/)).toBeInTheDocument();
    expect(screen.getByText(/按约 5 分钟聚合/)).toBeInTheDocument();
    expect(screen.getByText(/缓存命中率 76.0%/)).toBeInTheDocument();
    expect(screen.getByText('缓存命中 token')).toBeInTheDocument();
    expect(screen.getByLabelText('选择时间范围内 token 用量与缓存命中折线图')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('1,109,150')).toBeInTheDocument();
    expect(screen.getByText('900,000')).toBeInTheDocument();
    expect(screen.getByText('530')).toBeInTheDocument();
    expect(screen.getByText(/有效峰值 1,109,150/)).toBeInTheDocument();
  });
});
