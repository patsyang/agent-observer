import { useState } from 'react';
import { Search, X } from 'lucide-react';

import type { EnrichmentAvailability, EnrichmentJob } from '../api/types';

interface Props {
  signalId: string;
  availability: EnrichmentAvailability;
  requestEnrichment: (signalId: string, capabilityId: string) => Promise<EnrichmentJob>;
  cancelEnrichment: (jobId: string) => Promise<EnrichmentJob>;
  onChanged?: () => Promise<void>;
}

type MutationState = 'idle' | 'submitting' | 'success' | 'error';

export function EnrichmentPanel({ signalId, availability, requestEnrichment, cancelEnrichment, onChanged }: Props) {
  const [activeJob, setActiveJob] = useState<EnrichmentJob | null>(availability.active_job ?? null);
  const [mutationState, setMutationState] = useState<MutationState>('idle');
  const [message, setMessage] = useState<string | null>(null);

  const hasAvailableCapability = availability.capabilities.some((c) => c.state !== 'unavailable');
  const hasActiveJob = Boolean(activeJob || availability.active_job);
  if (!hasAvailableCapability && !hasActiveJob) {
    return null;
  }

  return (
    <section aria-label="补充排查上下文" data-testid="enrichment-panel">
      <h3>补充排查上下文</h3>
      {activeJob && (
        <div className="enrichment-status">
          <p>
            补证 {enrichmentJobStatusLabel(activeJob.status)}
            {activeJob.reason_code ? `，${reasonCodeLabel(activeJob.reason_code)}` : ''}
          </p>
          {activeJob.status === 'queued' && (
            <button className="compact-button" disabled={mutationState === 'submitting'} onClick={() => runCancel(activeJob.job_id)}>
              <X aria-hidden="true" size={15} />
              取消
            </button>
          )}
        </div>
      )}
      <ul className="enrichment-list">
        {availability.capabilities.map((capability) => (
          <li key={capability.capability_id}>
            <div className="enrichment-item__main">
              <strong>{capability.label}</strong>
              <span>
                {capabilityStateLabel(capability.state)}
                {capability.reason_code ? `，${reasonCodeLabel(capability.reason_code)}` : ''}
              </span>
            </div>
            <button
              className="compact-button primary"
              data-testid="request-enrichment"
              disabled={Boolean(activeJob) || capability.state === 'unavailable' || mutationState === 'submitting'}
              onClick={() => runRequest(capability.capability_id)}
            >
              <Search aria-hidden="true" size={15} />
              补充工具失败上下文
            </button>
          </li>
        ))}
      </ul>
      {message && <p role={mutationState === 'error' ? 'alert' : 'status'}>{message}</p>}
    </section>
  );

  async function runRequest(capabilityId: string) {
    setMutationState('submitting');
    setMessage(null);
    try {
      const job = await requestEnrichment(signalId, capabilityId);
      setActiveJob(job);
      setMutationState('success');
      setMessage(`补证 ${enrichmentJobStatusLabel(job.status)}`);
      await onChanged?.();
    } catch {
      setMutationState('error');
      setMessage('补证请求失败。请确认采集器在线且策略允许后重试。');
    }
  }

  async function runCancel(jobId: string) {
    setMutationState('submitting');
    setMessage(null);
    try {
      const job = await cancelEnrichment(jobId);
      setActiveJob(job);
      setMutationState('success');
      setMessage(`补证 ${enrichmentJobStatusLabel(job.status)}`);
      await onChanged?.();
    } catch {
      setMutationState('error');
      setMessage('取消补证失败。只有排队中的补证任务可以取消。');
    }
  }
}

function capabilityStateLabel(state: string): string {
  const labels: Record<string, string> = {
    available: '可执行',
    queueable: '可排队',
    unavailable: '不可用'
  };
  return labels[state] ?? state;
}

function enrichmentJobStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '已排队',
    pending: '排队中',
    running: '执行中',
    succeeded: '成功',
    failed: '失败',
    canceled: '已取消',
    cancelled: '已取消',
    expired: '已过期'
  };
  return labels[status] ?? status;
}

function reasonCodeLabel(reason: string): string {
  const labels: Record<string, string> = {
    collector_offline: '采集器离线',
    source_locked: '数据源锁定',
    policy_stale: '策略待刷新',
    heartbeat_stale: '心跳已过期',
  };
  return labels[reason] ?? reason;
}
