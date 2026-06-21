import { useEffect, useState } from 'react';

import type { ClientPackageConfig, EffectivePolicy, RecentAuditSummary } from '../api/types';
import { formatNumber } from '../utils/numberFormat';

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
  }) => Promise<EffectivePolicy>;
  loadAudit: () => Promise<RecentAuditSummary>;
  downloadUrl: string;
}

export function AccessConfigDrawer({ onClose, loadConfig, loadPolicy, savePolicy, loadAudit, downloadUrl }: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [enrichmentMode, setEnrichmentMode] = useState<'disabled' | 'enabled'>('enabled');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadConfig(), loadPolicy(), loadAudit()])
      .then(([packageConfig, policy, audit]) => {
        if (cancelled) return;
        setEnrichmentMode(policy.enrichment_mode);
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
            <span>接入配置</span>
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
            <dt>接入策略版本</dt>
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
                enrichment_mode: enrichmentMode
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
              <p>仅下载客户端时不需要保存接入策略。解压后运行同目录的配置和入口文件。</p>
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
                {saveState === 'saving' ? '正在保存接入策略' : '保存接入策略'}
              </button>
              <span>保存后影响新下载客户端；在线客户端会在下一次心跳后拉取最新策略。</span>
            </div>
            {saveState === 'saved' && <p role="status">接入策略已保存为 v{formatNumber(state.policy.policy_version)}</p>}
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
