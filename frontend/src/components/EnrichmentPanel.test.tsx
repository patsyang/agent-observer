import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { EnrichmentPanel } from './EnrichmentPanel';

describe('EnrichmentPanel', () => {
  it('renders available enrichments and requests a enabled capability', async () => {
    const requestEnrichment = vi.fn(async () => ({
      job_id: 'enrichment-job-001',
      status: 'pending',
      capability_id: 'codex_tool_failure_context'
    }));

    render(
      <EnrichmentPanel
        storyId="story-001"
        availability={{
          capabilities: [
            {
              capability_id: 'codex_tool_failure_context',
      label: '工具失败上下文补证',
              state: 'available',
              reason_code: null
            }
          ]
        }}
        requestEnrichment={requestEnrichment}
        cancelEnrichment={vi.fn()}
      />
    );

    expect(screen.getByText('工具失败上下文补证')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '补充工具失败上下文' }));

    expect(requestEnrichment).toHaveBeenCalledWith('story-001', 'codex_tool_failure_context');
    expect(await screen.findByRole('status')).toHaveTextContent(/补证 排队中/);
  });

  it('renders queueable, unavailable and cancellation states without arbitrary command input', async () => {
    const cancelEnrichment = vi.fn(async () => ({
      job_id: 'enrichment-job-002',
      status: 'cancelled',
      capability_id: 'codex_tool_failure_context'
    }));

    render(
      <EnrichmentPanel
        storyId="story-001"
        availability={{
          active_job: { job_id: 'enrichment-job-002', status: 'queued', capability_id: 'codex_tool_failure_context' },
          capabilities: [
            {
              capability_id: 'codex_tool_failure_context',
              label: '工具失败上下文补证',
              state: 'queueable',
              reason_code: 'collector_offline'
            },
            {
              capability_id: 'codex_locked_source',
              label: 'Locked source check',
              state: 'unavailable',
              reason_code: 'source_locked'
            }
          ]
        }}
        requestEnrichment={vi.fn()}
        cancelEnrichment={cancelEnrichment}
      />
    );

    expect(screen.getByText(/采集器离线/)).toBeInTheDocument();
    expect(screen.getByText('Locked source check')).toBeInTheDocument();
    expect(screen.queryByText('锁定数据源检查')).not.toBeInTheDocument();
    expect(screen.getByText(/数据源锁定/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/command/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(cancelEnrichment).toHaveBeenCalledWith('enrichment-job-002');
    expect(await screen.findByRole('status')).toHaveTextContent(/补证 已取消/);
  });
});
