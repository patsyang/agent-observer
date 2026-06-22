import type { CollectorsResponse, FactsResponse } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { collectorRuntimeLabel, qualitySummary, queueSummary, reasonCodeLabel, sumBacklog } from './dashboardLabels';

interface Props {
  activeSignalCount: number;
  collectors: CollectorsResponse;
  facts: FactsResponse;
  onlineCount: number;
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function DashboardAccessPanel({ activeSignalCount, collectors, facts, onlineCount }: Props) {
  return (
    <section className="sidebar-context" aria-label="接入与筛选" data-testid="dashboard-sidebar-context">
      <div className="sidebar-context__header">
        <h2>接入与筛选</h2>
        <span className={onlineCount ? 'badge green' : 'badge amber'}>
          {onlineCount ? '已收到心跳' : '等待采集器'}
        </span>
      </div>
      <div className="context-stack">
        <Mini label="命中质量" value={qualitySummary(facts)} />
        <Mini label="待传 outbox" value={formatNumber(sumBacklog(collectors))} />
        <Mini label="重点队列" value={queueSummary(activeSignalCount)} />
      </div>
      {collectors.collectors.length === 0 ? (
        <p>还没有采集器注册。请下载 Windows 包并运行 start。</p>
      ) : (
        <div className="sidebar-collector-list">
          {collectors.collectors.slice(0, 3).map((collector) => (
            <div className="sidebar-collector" key={collector.collector_id}>
              <strong>{collector.display_name}</strong>
              <span>{collectorRuntimeLabel(collector.source_status, collector.runtime_phase)} / {reasonCodeLabel(collector.reason_code)}</span>
              <small>backlog {formatNumber(collector.outbox_backlog)}</small>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
