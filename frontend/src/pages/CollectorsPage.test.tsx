import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { vi } from 'vitest';

import { sourceStatuses, type Collector } from '../api/types';
import { CollectorsPage } from './CollectorsPage';

function collector(status: Collector['source_status']): Collector {
  return {
    collector_id: `collector-${status}`,
    display_name: `Collector ${status}`,
    hostname_hash: 'host-hash',
    windows_username_hash: 'user-hash',
    agent_type: 'codex',
    protocol_version: 'agent-observer-telemetry/v2',
    agent_version: '0.2.0',
    source_status: status,
    reason_code: status,
    policy_version: 1,
    last_heartbeat_at: '2026-06-18T00:00:00Z',
    outbox_backlog: status === 'degraded' ? 5 : 0
  };
}

describe('CollectorsPage', () => {
  it('renders every source status reason from API data', async () => {
    render(
      <CollectorsPage
        loadCollectors={async () => ({
          collectors: sourceStatuses.map(collector)
        })}
        deleteCollector={async () => ({ collector_id: 'collector-offline', removed: true, reason_code: 'operator_cleanup' })}
      />
    );

    for (const status of sourceStatuses) {
      expect(await screen.findByText(status)).toBeInTheDocument();
    }
    expect(screen.getAllByText('v1').length).toBe(sourceStatuses.length);
    expect(screen.getByText('Collector online')).toBeInTheDocument();
  });

  it('cleans offline collectors from the management list without exposing remote stop controls', async () => {
    const user = userEvent.setup();
    const deleteCollector = vi.fn(async () => ({
      collector_id: 'collector-offline',
      removed: true,
      reason_code: 'operator_cleanup'
    }));

    render(
      <CollectorsPage
        loadCollectors={async () => ({ collectors: [collector('online'), collector('offline')] })}
        deleteCollector={deleteCollector}
      />
    );

    expect(await screen.findByText('Collector offline')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '清理 Collector online' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '清理 Collector offline' }));

    expect(deleteCollector).toHaveBeenCalledWith('collector-offline');
    expect(await screen.findByText('已清理 Collector offline')).toBeInTheDocument();
    expect(screen.queryByText('Collector offline')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /停止/ })).not.toBeInTheDocument();
  });

  it('shows raw upload as fixed enabled without per-collector toggles', async () => {
    render(
      <CollectorsPage
        loadCollectors={async () => ({ collectors: [collector('online'), collector('offline')] })}
        deleteCollector={async () => ({ collector_id: 'collector-offline', removed: true, reason_code: 'operator_cleanup' })}
      />
    );

    expect(await screen.findByText('Collector online')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /原文上报/ })).not.toBeInTheDocument();
    expect(screen.getAllByText('已开启').length).toBe(2);
    expect(screen.getAllByText('固定策略').length).toBe(2);
  });
});
