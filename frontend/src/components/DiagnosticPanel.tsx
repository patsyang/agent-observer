import { useState } from 'react';
import { Search, X } from 'lucide-react';

import type { DiagnosticAvailability, DiagnosticJob } from '../api/types';

interface Props {
  storyId: string;
  availability: DiagnosticAvailability;
  requestDiagnostic: (storyId: string, capabilityId: string) => Promise<DiagnosticJob>;
  cancelDiagnostic: (jobId: string) => Promise<DiagnosticJob>;
  onChanged?: () => Promise<void>;
}

type MutationState = 'idle' | 'submitting' | 'success' | 'error';

export function DiagnosticPanel({ storyId, availability, requestDiagnostic, cancelDiagnostic, onChanged }: Props) {
  const [activeJob, setActiveJob] = useState<DiagnosticJob | null>(availability.active_job ?? null);
  const [mutationState, setMutationState] = useState<MutationState>('idle');
  const [message, setMessage] = useState<string | null>(null);

  return (
    <section aria-label="诊断操作">
      <h3>诊断</h3>
      {activeJob && (
        <div className="diagnostic-status">
          <p>
            诊断 {diagnosticJobStatusLabel(activeJob.status)}
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
      <ul className="diagnostic-list">
        {availability.capabilities.map((capability) => (
          <li key={capability.capability_id}>
            <div className="diagnostic-item__main">
              <strong>{capabilityLabel(capability.capability_id, capability.label)}</strong>
              <span>
                {capabilityStateLabel(capability.state)}
                {capability.reason_code ? `，${reasonCodeLabel(capability.reason_code)}` : ''}
              </span>
            </div>
            <button
              className="compact-button primary"
              disabled={capability.state === 'unavailable' || mutationState === 'submitting'}
              onClick={() => runRequest(capability.capability_id)}
            >
              <Search aria-hidden="true" size={15} />
              补充上下文
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
      const job = await requestDiagnostic(storyId, capabilityId);
      setActiveJob(job);
      setMutationState('success');
      setMessage(`诊断 ${diagnosticJobStatusLabel(job.status)}`);
      await onChanged?.();
    } catch {
      setMutationState('error');
      setMessage('诊断请求失败。请确认采集器和策略允许后重试。');
    }
  }

  async function runCancel(jobId: string) {
    setMutationState('submitting');
    setMessage(null);
    try {
      const job = await cancelDiagnostic(jobId);
      setActiveJob(job);
      setMutationState('success');
      setMessage(`诊断 ${diagnosticJobStatusLabel(job.status)}`);
      await onChanged?.();
    } catch {
      setMutationState('error');
      setMessage('取消诊断失败。只有排队中的诊断可以取消。');
    }
  }
}

function capabilityLabel(capabilityId: string, fallback: string): string {
  const labels: Record<string, string> = {
    codex_error_context: 'Codex 错误上下文',
    codex_locked_source: '锁定数据源检查'
  };
  return labels[capabilityId] ?? fallback;
}

function capabilityStateLabel(state: string): string {
  const labels: Record<string, string> = {
    available: '可执行',
    queueable: '可排队',
    unavailable: '不可用'
  };
  return labels[state] ?? state;
}

function diagnosticJobStatusLabel(status: string): string {
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
    policy_not_fetched: '未拉取策略',
    heartbeat_stale: '心跳已过期',
  };
  return labels[reason] ?? reason;
}
