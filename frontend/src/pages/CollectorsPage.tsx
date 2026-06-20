import { useEffect, useState } from 'react';
import { Trash2 } from 'lucide-react';

import { sourceStatuses, type Collector, type CollectorsResponse, type SourceStatus } from '../api/types';
import { formatNumber } from '../utils/numberFormat';

const statusLabels: Record<SourceStatus, string> = {
  online: '在线',
  degraded: '异常但进程仍在',
  offline: '离线',
  source_missing: '数据源缺失',
  source_locked: '数据源锁定'
};

export function CollectorsPage({
  deleteCollector,
  loadCollectors,
  updateRawUpload
}: {
  deleteCollector: (collectorId: string) => Promise<{ collector_id: string; removed: boolean; reason_code: string }>;
  loadCollectors: () => Promise<CollectorsResponse>;
  updateRawUpload: (
    collectorId: string,
    enabled: boolean
  ) => Promise<{ collector_id: string; raw_upload_enabled: boolean; raw_upload_override: boolean; raw_upload_source: string }>;
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [collectors, setCollectors] = useState<Collector[]>([]);
  const [cleanupMessage, setCleanupMessage] = useState<string | null>(null);
  const [cleanupError, setCleanupError] = useState<string | null>(null);
  const [rawMessage, setRawMessage] = useState<string | null>(null);

  useEffect(() => {
    loadCollectors()
      .then((data) => {
        setCollectors(data.collectors);
        setState(data.collectors.length ? 'ready' : 'empty');
      })
      .catch(() => setState('error'));
  }, [loadCollectors]);

  if (state === 'loading') return <section className="panel">正在加载采集器</section>;
  if (state === 'error') return <section className="panel">采集器状态不可用</section>;
  if (state === 'empty') {
    return (
      <section className="panel">
        <h2>采集器</h2>
        <p>还没有采集器注册。请从“下载与策略配置”下载 Windows 包并运行 start。</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>采集器</h2>
      <p className="panel-intro">
        这里用于查看本机 collector 接入状态。在线客户端可开启或关闭原文上报；清理只会从管理列表移除离线或遗留采集器。
      </p>
      {cleanupMessage && <p role="status">{cleanupMessage}</p>}
      {rawMessage && <p role="status">{rawMessage}</p>}
      {cleanupError && <p role="alert">{cleanupError}</p>}
      <div className="status-legend" aria-label="支持的数据源状态">
        {sourceStatuses.map((status) => (
          <span key={status}>{statusLabels[status]}</span>
        ))}
      </div>
      <table className="responsive-table">
        <thead>
          <tr>
            <th>采集器</th>
            <th>客户端</th>
            <th>策略</th>
            <th>数据源状态</th>
            <th>原因</th>
            <th>待传</th>
            <th>原文上报</th>
            <th>管理</th>
          </tr>
        </thead>
        <tbody>
          {collectors.map((collector) => (
            <tr key={collector.collector_id}>
              <td data-label="采集器">
                <strong>{collector.display_name}</strong>
                <small>{collector.collector_id}</small>
              </td>
              <td data-label="客户端">{collector.agent_type} {collector.agent_version}</td>
              <td data-label="策略">v{formatNumber(collector.policy_version)}</td>
              <td data-label="数据源状态">{statusLabels[collector.source_status]}</td>
              <td data-label="原因">{collector.reason_code}</td>
              <td data-label="待传">{formatNumber(collector.outbox_backlog)}</td>
              <td data-label="原文上报">
                <label className="toggle-cell">
                  <input
                    aria-label={`原文上报 ${collector.display_name}`}
                    checked={collector.raw_upload_enabled}
                    disabled={collector.source_status !== 'online'}
                    type="checkbox"
                    onChange={() => toggleRawUpload(collector)}
                  />
                  <span>{collector.raw_upload_enabled ? '已开' : '未开'}</span>
                </label>
                <small>{rawSourceText(collector)}</small>
              </td>
              <td data-label="管理">
                <button
                  aria-label={`清理 ${collector.display_name}`}
                  className="icon-button"
                  disabled={collector.source_status === 'online'}
                  onClick={() => cleanupCollector(collector)}
                >
                  <Trash2 aria-hidden="true" size={15} />
                  清理
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );

  async function cleanupCollector(collector: Collector) {
    setCleanupMessage(null);
    setCleanupError(null);
    try {
      await deleteCollector(collector.collector_id);
      setCollectors((current) => current.filter((item) => item.collector_id !== collector.collector_id));
      setCleanupMessage(`已清理 ${collector.display_name}`);
    } catch {
      setCleanupError('采集器清理失败。请刷新后确认该采集器是否仍存在。');
    }
  }

  async function toggleRawUpload(collector: Collector) {
    setRawMessage(null);
    setCleanupError(null);
    try {
      const updated = await updateRawUpload(collector.collector_id, !collector.raw_upload_enabled);
      setCollectors((current) => current.map((item) => (
        item.collector_id === collector.collector_id
          ? {
              ...item,
              raw_upload_enabled: updated.raw_upload_enabled,
              raw_upload_override: updated.raw_upload_override,
              raw_upload_source: updated.raw_upload_source as Collector['raw_upload_source'],
            }
          : item
      )));
      setRawMessage(`${collector.display_name} 已${updated.raw_upload_enabled ? '开启' : '关闭'}原文上报`);
    } catch {
      setCleanupError('原文上报策略更新失败。请确认采集器在线后重试。');
    }
  }
}

function rawSourceText(collector: Collector): string {
  if (collector.raw_upload_source === 'collector_override' || collector.raw_upload_override) {
    return '单独配置';
  }
  return '跟随全局';
}
