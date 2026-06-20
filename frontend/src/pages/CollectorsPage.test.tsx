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
    agent_version: '0.1.0',
    source_status: status,
    reason_code: status,
    policy_version: 1,
    last_heartbeat_at: '2026-06-18T00:00:00Z',
    outbox_backlog: status === 'degraded' ? 5 : 0,
    raw_upload_enabled: false,
    raw_upload_override: false,
    raw_upload_source: 'global_policy'
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
        updateRawUpload={async () => ({
          collector_id: 'collector-online',
          raw_upload_enabled: true,
          raw_upload_override: true,
          raw_upload_source: 'collector_override'
        })}
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
        updateRawUpload={async () => ({
          collector_id: 'collector-online',
          raw_upload_enabled: true,
          raw_upload_override: true,
          raw_upload_source: 'collector_override'
        })}
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

  it('toggles raw upload only for online collectors', async () => {
    const user = userEvent.setup();
    const updateRawUpload = vi.fn(async () => ({
      collector_id: 'collector-online',
      raw_upload_enabled: true,
      raw_upload_override: true,
      raw_upload_source: 'collector_override'
    }));

    render(
      <CollectorsPage
        loadCollectors={async () => ({ collectors: [collector('online'), collector('offline')] })}
        deleteCollector={async () => ({ collector_id: 'collector-offline', removed: true, reason_code: 'operator_cleanup' })}
        updateRawUpload={updateRawUpload}
      />
    );

    expect(await screen.findByText('Collector online')).toBeInTheDocument();
    const rawUploadSwitches = screen.getAllByRole('checkbox', { name: /原文上报/ });
    expect(rawUploadSwitches[0]).toBeEnabled();
    expect(rawUploadSwitches[1]).toBeDisabled();
    await user.click(rawUploadSwitches[0]);

    expect(updateRawUpload).toHaveBeenCalledWith('collector-online', true);
    expect(await screen.findByText('Collector online 已开启原文上报')).toBeInTheDocument();
    expect(rawUploadSwitches[0]).toBeChecked();
  });
});
