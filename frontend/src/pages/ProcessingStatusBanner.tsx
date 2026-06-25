import type { ProcessingStatus } from '../api/types';
import { formatDateTime } from './dashboardLabels';

interface Props {
  status: ProcessingStatus;
}

function processingLabel(status: ProcessingStatus): string {
  return ({ idle: '空闲', pending: '待处理', running: '计算中', failed: '失败' } as const)[status.state];
}

export function ProcessingStatusBanner({ status }: Props) {
  return (
    <span className={`processing-status ${status.state}`} aria-label="派生计算状态">
      <span>派生计算：{processingLabel(status)}</span>
      {status.state === 'pending' || status.state === 'running' ? (
        <small>信号更新中</small>
      ) : null}
      {status.state === 'failed' && status.latest_failed ? (
        <small>{status.latest_failed.last_error}，最近失败 {formatDateTime(status.latest_failed.updated_at)}</small>
      ) : null}
    </span>
  );
}
