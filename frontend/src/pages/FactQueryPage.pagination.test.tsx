import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';

import { FactQueryPage } from './FactQueryPage';
import { detail } from './FactQueryPage.fixtures';

it('paginates facts and keeps selected fact after refresh', async () => {
    const user = userEvent.setup();
    const rows = Array.from({ length: 55 }, (_, index) => ({
      fact_id: `fact-${index + 1}`,
      fact_type: 'content',
      category: 'codex_prompt',
      quality: 'high' as const,
      severity: 'low',
      summary: `Prompt ${index + 1}`,
      occurred_at: '2026-06-18T10:00:00+00:00',
      source: 'codex',
      promoted_to_story: false,
      content_preview: `Prompt: 第 ${index + 1} 条`,
      raw_available: false,
      raw_status: '仅结构化字段'
    }));
    const loadFacts = vi.fn(async (filters) => ({
      facts: rows.slice(filters.offset, filters.offset + filters.limit),
      total: rows.length,
      limit: filters.limit,
      offset: filters.offset,
    }));
    const loadFactDetail = vi.fn(async (factId: string) => ({
      ...detail,
      fact: rows.find((row) => row.fact_id === factId) ?? rows[0],
      evidence_projection: { ...detail.evidence_projection, fact_id: factId },
    }));

    render(<FactQueryPage loadFacts={loadFacts} loadFactDetail={loadFactDetail} />);

    expect(await screen.findByText(/共 55 条/)).toBeInTheDocument();
    expect(screen.getByText(/第\s*1\s*-\s*50\s*条/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一页' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => expect(loadFacts).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 50, offset: 50 })));
    expect(await screen.findByText(/第\s*51\s*-\s*55\s*条/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '查看 fact-51' }));
    const detailPanel = await screen.findByLabelText('证据详情');
    expect(within(detailPanel).getByText(/第 51 条/)).toHaveTextContent('fact-51');
    await user.click(screen.getByRole('button', { name: '刷新' }));
    await waitFor(() => expect(loadFactDetail).toHaveBeenLastCalledWith('fact-51'));
    expect(screen.getByText(/最后刷新/)).toBeInTheDocument();
  });
