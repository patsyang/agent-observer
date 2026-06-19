import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DiagnosticPanel } from './DiagnosticPanel';

describe('DiagnosticPanel', () => {
  it('renders available diagnostics and requests a whitelisted capability', async () => {
    const requestDiagnostic = vi.fn(async () => ({
      job_id: 'diag-job-001',
      status: 'pending',
      capability_id: 'codex_error_context'
    }));

    render(
      <DiagnosticPanel
        storyId="story-001"
        availability={{
          capabilities: [
            {
              capability_id: 'codex_error_context',
              label: 'Collect Codex error context',
              state: 'available',
              reason_code: null
            }
          ]
        }}
        requestDiagnostic={requestDiagnostic}
        cancelDiagnostic={vi.fn()}
      />
    );

    await userEvent.click(screen.getByRole('button', { name: '补充上下文' }));

    expect(requestDiagnostic).toHaveBeenCalledWith('story-001', 'codex_error_context');
    expect(await screen.findByRole('status')).toHaveTextContent(/诊断 排队中/);
  });

  it('renders queueable, unavailable and cancellation states without arbitrary command input', async () => {
    const cancelDiagnostic = vi.fn(async () => ({
      job_id: 'diag-job-002',
      status: 'cancelled',
      capability_id: 'codex_error_context'
    }));

    render(
      <DiagnosticPanel
        storyId="story-001"
        availability={{
          active_job: { job_id: 'diag-job-002', status: 'queued', capability_id: 'codex_error_context' },
          capabilities: [
            {
              capability_id: 'codex_error_context',
              label: 'Collect Codex error context',
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
        requestDiagnostic={vi.fn()}
        cancelDiagnostic={cancelDiagnostic}
      />
    );

    expect(screen.getByText(/采集器离线/)).toBeInTheDocument();
    expect(screen.getByText(/数据源锁定/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/command/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(cancelDiagnostic).toHaveBeenCalledWith('diag-job-002');
    expect(await screen.findByRole('status')).toHaveTextContent(/诊断 已取消/);
  });
});
