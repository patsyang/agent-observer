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
    template_enabled: boolean;
    upload_raw: boolean;
    collection_policy: string;
    diagnostic_policy: string;
  }) => Promise<EffectivePolicy>;
  loadAudit: () => Promise<RecentAuditSummary>;
  downloadUrl: string;
}

export function AccessConfigDrawer({ onClose, loadConfig, loadPolicy, savePolicy, loadAudit, downloadUrl }: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [templateEnabled, setTemplateEnabled] = useState(true);
  const [uploadRaw, setUploadRaw] = useState(false);
  const [collectionPolicy, setCollectionPolicy] = useState('');
  const [diagnosticPolicy, setDiagnosticPolicy] = useState('');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadConfig(), loadPolicy(), loadAudit()])
      .then(([packageConfig, policy, audit]) => {
        if (cancelled) return;
        setTemplateEnabled(policy.template_enabled);
        setUploadRaw(policy.upload_raw);
        setCollectionPolicy(policy.collection_policy);
        setDiagnosticPolicy(policy.diagnostic_policy);
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
      <aside className="drawer" aria-label="下载与策略配置">
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
            <dd>http://127.0.0.1:8765</dd>
          </div>
          <div>
            <dt>策略写入</dt>
            <dd>服务端 effective_policy</dd>
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
                template_enabled: templateEnabled,
                upload_raw: uploadRaw,
                collection_policy: collectionPolicy,
                diagnostic_policy: diagnosticPolicy
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
              <p>仅下载客户端时不需要点击“保存策略”。解压后运行同目录的配置和入口文件。</p>
            </div>
            <a className="primary download-button" href={downloadUrl} download="agent-observer-windows.zip">
              下载 Windows 客户端
            </a>
            <dl className="package-grid">
              <div>
                <dt>安装包</dt>
                <dd>{state.packageConfig.filename}</dd>
              </div>
              <div>
                <dt>配置文件</dt>
                <dd>{state.packageConfig.config_path}</dd>
              </div>
              <div>
                <dt>校验摘要</dt>
                <dd>sha256 {state.packageConfig.sha256.slice(0, 8)}</dd>
              </div>
            </dl>
          </section>

          <section className="drawer-section" aria-label="策略开关">
            <div className="section-title-row">
              <h3>策略开关</h3>
              <span>v{formatNumber(state.policy.policy_version)}</span>
            </div>
            <label className="switch-row">
              <input
                aria-label="启用 Codex 来源模板"
                type="checkbox"
                checked={templateEnabled}
                onChange={(event) => setTemplateEnabled(event.target.checked)}
              />
              <span>
                <strong>启用 Codex 来源模板</strong>
                <small>采集器按内置 Codex 会话结构生成事实。</small>
              </span>
            </label>
            <label className="switch-row">
              <input
                aria-label="客户端下载默认上传原文"
                type="checkbox"
                checked={uploadRaw}
                onChange={(event) => setUploadRaw(event.target.checked)}
              />
              <span>
                <strong>客户端下载默认上传原文</strong>
                <small>新下载的 Windows 客户端会把该值写入配置；在线客户端可在采集器管理中单独开关。</small>
              </span>
            </label>
          </section>

          <section className="drawer-section" aria-label="策略文本">
            <h3>策略文本</h3>
            <label>
              采集策略
              <textarea value={collectionPolicy} onChange={(event) => setCollectionPolicy(event.target.value)} />
            </label>
            <label>
              诊断策略
              <textarea value={diagnosticPolicy} onChange={(event) => setDiagnosticPolicy(event.target.value)} />
            </label>
            <div className="drawer-actions">
              <button className="primary" disabled={saveState === 'saving'} type="submit">
                {saveState === 'saving' ? '正在保存策略' : '保存策略'}
              </button>
              <span>保存后影响后续采集器拉取的 effective_policy。</span>
            </div>
            {saveState === 'saved' && <p role="status">策略已保存为 v{formatNumber(state.policy.policy_version)}</p>}
            {saveState === 'error' && <p role="alert">策略更新失败。请重新打开配置后再试。</p>}
          </section>

          <section className="drawer-section audit-section" aria-label="策略审计">
            <h3>最近审计</h3>
            <p>{state.audit.latest}</p>
          </section>
        </form>
      )}
      </aside>
    </div>
  );
}
