import { useEffect, useState } from 'react';

import type { ClientPackageConfig, EffectivePolicy, RecentAuditSummary } from '../api/types';
import { formatNumber } from '../utils/numberFormat';

const DEFAULT_PERFORMANCE = {
  collection_interval_seconds: 10,
  max_events_per_cycle: 500,
  upload_batch_size: 100,
  worker_poll_interval_seconds: 10
};

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; packageConfig: ClientPackageConfig; policy: EffectivePolicy; audit: RecentAuditSummary };

interface Props {
  onClose: () => void;
  loadConfig: () => Promise<ClientPackageConfig>;
  loadPolicy: () => Promise<EffectivePolicy>;
  savePolicy: (policy: {
    expected_version: number;
    enrichment_mode: 'disabled' | 'enabled';
    collection_interval_seconds: number;
    max_events_per_cycle: number;
    upload_batch_size: number;
    worker_poll_interval_seconds: number;
  }) => Promise<EffectivePolicy>;
  loadAudit: () => Promise<RecentAuditSummary>;
  downloadUrl: string;
}

export function AccessConfigDrawer({ onClose, loadConfig, loadPolicy, savePolicy, loadAudit, downloadUrl }: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [enrichmentMode, setEnrichmentMode] = useState<'disabled' | 'enabled'>('enabled');
  const [performance, setPerformance] = useState(DEFAULT_PERFORMANCE);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadConfig(), loadPolicy(), loadAudit()])
      .then(([packageConfig, policy, audit]) => {
        if (cancelled) return;
        setEnrichmentMode(policy.enrichment_mode);
        setPerformance({
          collection_interval_seconds: policy.collection_interval_seconds,
          max_events_per_cycle: policy.max_events_per_cycle,
          upload_batch_size: policy.upload_batch_size,
          worker_poll_interval_seconds: policy.worker_poll_interval_seconds
        });
        setState({ status: 'ready', packageConfig, policy, audit });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [loadAudit, loadConfig, loadPolicy]);

  return (
    <div className="drawer-backdrop">
      <aside className="drawer" aria-label="下载与策略配置" data-testid="access-config-drawer">
        <header className="drawer-header">
          <div>
            <span>全局配置</span>
            <h2>Windows collector 客户端</h2>
            <p>下载包可直接使用；只有改策略时才需要保存。</p>
          </div>
          <button className="ghost-button" aria-label="关闭下载与策略配置" onClick={onClose} type="button">
            关闭
          </button>
        </header>
        <dl className="drawer-meta">
          <div>
            <dt>服务地址</dt>
            <dd>{state.status === 'ready' ? state.packageConfig.server_url : 'http://127.0.0.1:8765'}</dd>
          </div>
          <div>
            <dt>策略版本</dt>
            <dd>{state.status === 'ready' ? `v${formatNumber(state.policy.policy_version)}` : '-'}</dd>
          </div>
        </dl>
      {state.status === 'loading' && <p>正在加载安装包和策略</p>}
      {state.status === 'error' && <p role="alert">配置不可用。请确认后端服务运行后重试。</p>}
      {state.status === 'ready' && (
        <form
          className="drawer-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setSaveState('saving');
            try {
              const policy = await savePolicy({
                expected_version: state.policy.policy_version,
                enrichment_mode: enrichmentMode,
                ...performance
              });
              const audit = await loadAudit();
              setState({ status: 'ready', packageConfig: state.packageConfig, policy, audit });
              setSaveState('saved');
            } catch {
              setSaveState('error');
            }
          }}
        >
          <section className="drawer-section hero-section" aria-label="客户端下载">
            <div>
              <h3>下载客户端</h3>
              <p>仅下载客户端时不需要保存全局配置。解压后运行同目录的配置和入口文件。</p>
            </div>
            <a className="primary download-button" data-testid="download-client" href={downloadUrl} download="agent-observer-windows.zip">
              下载 Windows 客户端
            </a>
            <dl className="package-grid">
              <div>
                <dt>安装包</dt>
                <dd>{state.packageConfig.filename}</dd>
              </div>
              <div>
                <dt>客户端版本</dt>
                <dd>{state.packageConfig.agent_version}</dd>
              </div>
              <div>
                <dt>协议版本</dt>
                <dd>{state.packageConfig.protocol_version}</dd>
              </div>
              <div>
                <dt>校验摘要</dt>
                <dd>sha256 {state.packageConfig.sha256.slice(0, 8)}</dd>
              </div>
            </dl>
          </section>

          <section className="drawer-section" aria-label="采集性能">
            <div className="section-title-row">
              <h3>采集性能</h3>
              <button className="ghost-button" type="button" onClick={() => setPerformance(DEFAULT_PERFORMANCE)}>
                恢复默认值
              </button>
            </div>
            <div className="performance-grid">
              <label>
                <span>采集间隔</span>
                <input
                  aria-label="采集间隔"
                  max={300}
                  min={1}
                  type="number"
                  value={performance.collection_interval_seconds}
                  onChange={(event) => setPerformance({ ...performance, collection_interval_seconds: Number(event.target.value) })}
                />
                <small>秒</small>
              </label>
              <label>
                <span>单轮采集上限</span>
                <input
                  aria-label="单轮采集上限"
                  max={5000}
                  min={100}
                  type="number"
                  value={performance.max_events_per_cycle}
                  onChange={(event) => setPerformance({ ...performance, max_events_per_cycle: Number(event.target.value) })}
                />
                <small>条/Agent</small>
              </label>
              <label>
                <span>上传批量</span>
                <input
                  aria-label="上传批量"
                  max={500}
                  min={20}
                  type="number"
                  value={performance.upload_batch_size}
                  onChange={(event) => setPerformance({ ...performance, upload_batch_size: Number(event.target.value) })}
                />
                <small>条/请求</small>
              </label>
            </div>
            <p>保存后对新版在线客户端生效；客户端会在下一次心跳或下一轮采集前应用。</p>
          </section>

          <section className="drawer-section" aria-label="服务端处理">
            <div className="section-title-row">
              <h3>服务端处理</h3>
            </div>
            <div className="performance-grid">
              <label>
                <span>Worker 轮询间隔</span>
                <input
                  aria-label="Worker 轮询间隔"
                  max={300}
                  min={2}
                  type="number"
                  value={performance.worker_poll_interval_seconds}
                  onChange={(event) => setPerformance({ ...performance, worker_poll_interval_seconds: Number(event.target.value) })}
                />
                <small>秒</small>
              </label>
            </div>
            <p>保存后后端 worker 会在下一次空闲轮询前读取最新策略。</p>
          </section>

          <section className="drawer-section" aria-label="参数关系" data-testid="access-param-relations">
            <h3>参数关系</h3>
            <p>
              采集间隔 × 单轮采集上限 = 每个 Agent 的理论吞吐上限（条/分钟）；单轮采集上限 ÷ 上传批量 = 单轮需要发起的 HTTP 请求数。
            </p>
            <p>
              Worker 轮询间隔建议不超过采集间隔的 2 倍，否则 processing_jobs 队列会积压。采集间隔建议保持在 5–60 秒之间，过小会浪费 CPU/IO，过大会延迟看到数据；Worker 轮询间隔大于 30 秒会延迟看到风险信号。
            </p>
          </section>

          <section className="drawer-section" aria-label="采集内容">
            <div className="section-title-row">
              <h3>采集内容</h3>
            </div>
            <div className="switch-row">
              <span>
                <strong>默认上传原始输入输出</strong>
                <small>当前版本固定上传完整 Prompt 和响应内容，用于会话查询和信号排查；暂不支持关闭。</small>
              </span>
            </div>
            <label className="switch-row">
              <input
                aria-label="允许本机补证任务"
                type="checkbox"
                checked={enrichmentMode === 'enabled'}
                onChange={(event) => setEnrichmentMode(event.target.checked ? 'enabled' : 'disabled')}
              />
              <span>
                <strong>允许本机补证任务</strong>
                <small>开启后服务端可下发内置只读补证任务；客户端不会执行任意命令。</small>
              </span>
            </label>
            <div className="drawer-actions">
              <button className="primary" data-testid="save-policy" disabled={saveState === 'saving'} type="submit">
                {saveState === 'saving' ? '正在保存全局配置' : '保存并下发配置'}
              </button>
              <span>新版在线客户端将在下一次心跳或下一轮采集前生效。</span>
            </div>
            {saveState === 'saved' && <p role="status">全局配置已保存为 v{formatNumber(state.policy.policy_version)}</p>}
            {saveState === 'error' && <p role="alert">策略更新失败。请重新打开配置后再试。</p>}
          </section>

          <section className="drawer-section audit-section" aria-label="策略审计" data-testid="access-audit">
            <h3>最近审计</h3>
            <p>{state.audit.latest}</p>
          </section>
        </form>
      )}
      </aside>
    </div>
  );
}
