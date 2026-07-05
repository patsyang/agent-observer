import { useState } from 'react';
import { ActivitySquare, LayoutDashboard, MessagesSquare, Radio } from 'lucide-react';

import {
  clientPackageUrl,
  cancelEnrichment,
  deleteCollector,
  fetchDashboardSummary,
  fetchClientPackageConfig,
  fetchCollectors,
  fetchConversationDetail,
  fetchConversationForFact,
  fetchConversations,
  fetchEnrichmentAvailability,
  fetchPolicy,
  fetchProcessingStatus,
  fetchRecentAudit,
  fetchRiskSummary,
  fetchSignals,
  fetchSignalDetail,
  fetchSignalsSummary,
  fetchUsageSummary,
  handleSignal,
  markSignalRead,
  requestEnrichment,
  updatePolicy
} from './api/client';
import { AccessConfigDrawer } from './components/AccessConfigDrawer';
import { CollectorsPage } from './pages/CollectorsPage';
import { ConversationQueryPage } from './pages/ConversationQueryPage';
import { DashboardPage } from './pages/DashboardPage';
import { SignalDetailPage } from './pages/SignalDetailPage';

type View = 'dashboard' | 'collectors' | 'conversations';

const navItems: Array<{ view: View; label: string; desc: string; icon: typeof LayoutDashboard }> = [
  { view: 'dashboard', label: '观测总览', desc: '信号与用量', icon: LayoutDashboard },
  { view: 'conversations', label: '会话查询', desc: '输入与响应', icon: MessagesSquare },
  { view: 'collectors', label: '采集器', desc: '状态与策略', icon: Radio }
];

export function App() {
  const [view, setView] = useState<View>('dashboard');
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [selectedFactId, setSelectedFactId] = useState<string | null>(null);
  const [returnSignalId, setReturnSignalId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="主导航">
        <div className="brand">
          <div className="brand-mark">AO</div>
          <div className="brand-copy">
            <strong>Agent Observer</strong>
            <span>终端智能体运行观测</span>
          </div>
        </div>
        <nav className="side-nav" aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
            <button
              className={view === item.view ? 'active' : ''}
              data-testid={`nav-${item.view}`}
              key={item.view}
              onClick={() => {
                setSelectedSignalId(null);
                setSelectedFactId(null);
                setReturnSignalId(null);
                setView(item.view);
              }}
            >
              <Icon aria-hidden="true" size={18} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.desc}</small>
              </span>
            </button>
            );
          })}
        </nav>
        <section className="side-card">
          <span>当前项目</span>
          <strong>agent-observer</strong>
          <small>collector / 本地观测上报</small>
        </section>
        <button className="primary full-width" data-testid="open-access-config" onClick={() => setDrawerOpen(true)}>
          <ActivitySquare aria-hidden="true" size={16} />
          全局配置
        </button>
        <div className="sidebar-dashboard-slot" id="dashboard-sidebar-slot" />
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{view === 'dashboard' ? '观测总览' : view === 'conversations' ? '会话查询' : '采集器'}</h1>
            <p>围绕信号、会话输入输出和 collector 接入状态进行日常排查。</p>
          </div>
          {view === 'dashboard' && <div className="topbar-status-slot" id="dashboard-topbar-status-slot" />}
        </header>
        {view === 'dashboard' && selectedSignalId === null && (
          <DashboardPage
            loadDashboardSummary={fetchDashboardSummary}
            loadSignals={fetchSignals}
            loadSignalSummary={fetchSignalsSummary}
            loadUsageSummary={fetchUsageSummary}
            loadRiskSummary={fetchRiskSummary}
            loadProcessingStatus={fetchProcessingStatus}
            onOpenSignal={setSelectedSignalId}
          />
        )}
        {view === 'dashboard' && selectedSignalId !== null && (
          <SignalDetailPage
            signalId={selectedSignalId}
            loadSignalDetail={fetchSignalDetail}
            loadConversationDetail={fetchConversationDetail}
            loadEnrichmentAvailability={fetchEnrichmentAvailability}
            markRead={markSignalRead}
            handleSignal={handleSignal}
            requestEnrichment={requestEnrichment}
            cancelEnrichment={cancelEnrichment}
            onBack={() => setSelectedSignalId(null)}
            onOpenFact={(factId) => {
              setSelectedFactId(factId);
              setReturnSignalId(selectedSignalId);
              setSelectedSignalId(null);
              setView('conversations');
            }}
          />
        )}
        {view === 'conversations' && (
          <ConversationQueryPage
            initialFactId={selectedFactId}
            loadConversationDetail={fetchConversationDetail}
            loadConversationForFact={fetchConversationForFact}
            loadConversations={fetchConversations}
            onBack={returnSignalId ? () => {
              setSelectedFactId(null);
              setSelectedSignalId(returnSignalId);
              setReturnSignalId(null);
              setView('dashboard');
            } : undefined}
            backLabel="返回信号"
          />
        )}
        {view === 'collectors' && (
          <CollectorsPage
            loadCollectors={fetchCollectors}
            deleteCollector={deleteCollector}
          />
        )}
        {drawerOpen && (
          <AccessConfigDrawer
            onClose={() => setDrawerOpen(false)}
            loadConfig={fetchClientPackageConfig}
            loadPolicy={fetchPolicy}
            savePolicy={updatePolicy}
            loadAudit={fetchRecentAudit}
            downloadUrl={clientPackageUrl()}
          />
        )}
      </main>
    </div>
  );
}
