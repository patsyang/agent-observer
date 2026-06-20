import { useState } from 'react';
import { ActivitySquare, DatabaseZap, LayoutDashboard, Radio } from 'lucide-react';

import {
  clientPackageUrl,
  cancelDiagnostic,
  deleteCollector,
  fetchDashboardSummary,
  fetchClientPackageConfig,
  fetchCollectors,
  fetchDiagnosticAvailability,
  fetchFactDetail,
  fetchFacts,
  fetchPolicy,
  fetchRecentAudit,
  fetchRiskSummary,
  fetchStories,
  fetchStoryDetail,
  fetchUsageSummary,
  handleStory,
  markStoryRead,
  requestDiagnostic,
  updateCollectorRawUpload,
  updatePolicy
} from './api/client';
import { AccessConfigDrawer } from './components/AccessConfigDrawer';
import { CollectorsPage } from './pages/CollectorsPage';
import { DashboardPage } from './pages/DashboardPage';
import { FactQueryPage, type InitialFactFilters } from './pages/FactQueryPage';
import { ObservationStoryDetailPage } from './pages/ObservationStoryDetailPage';

type View = 'dashboard' | 'collectors' | 'facts';

const navItems: Array<{ view: View; label: string; desc: string; icon: typeof LayoutDashboard }> = [
  { view: 'dashboard', label: '观测总览', desc: '故事与风险', icon: LayoutDashboard },
  { view: 'facts', label: '事实查询', desc: '证据与原文', icon: DatabaseZap },
  { view: 'collectors', label: '采集器', desc: '状态与策略', icon: Radio }
];

export function App() {
  const [view, setView] = useState<View>('dashboard');
  const [selectedStoryId, setSelectedStoryId] = useState<string | null>(null);
  const [selectedFactId, setSelectedFactId] = useState<string | null>(null);
  const [initialFactFilters, setInitialFactFilters] = useState<InitialFactFilters | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="主导航">
        <div className="brand">
          <div className="brand-mark">AO</div>
          <div>
            <strong>Agent Observer</strong>
            <span>本地智能体观测台</span>
          </div>
        </div>
        <nav className="side-nav" aria-label="主导航">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
            <button
              className={view === item.view ? 'active' : ''}
              key={item.view}
              onClick={() => {
                setSelectedStoryId(null);
                setSelectedFactId(null);
                setInitialFactFilters(null);
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
          <small>collector / 本地事实上报</small>
        </section>
        <button className="primary full-width" onClick={() => setDrawerOpen(true)}>
          <ActivitySquare aria-hidden="true" size={16} />
          接入配置
        </button>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{view === 'dashboard' ? '观测总览' : view === 'facts' ? '事实查询' : '采集器'}</h1>
            <p>围绕故事处理、证据追溯和 collector 接入状态进行日常排查。</p>
          </div>
        </header>
        {view === 'dashboard' && selectedStoryId === null && (
          <DashboardPage
            loadDashboardSummary={fetchDashboardSummary}
            loadStories={fetchStories}
            loadUsageSummary={fetchUsageSummary}
            loadRiskSummary={fetchRiskSummary}
            onOpenStory={setSelectedStoryId}
            onOpenFacts={(filters) => {
              setSelectedFactId(null);
              setInitialFactFilters(filters);
              setView('facts');
            }}
          />
        )}
        {view === 'dashboard' && selectedStoryId !== null && (
          <ObservationStoryDetailPage
            storyId={selectedStoryId}
            loadStoryDetail={fetchStoryDetail}
            loadDiagnosticAvailability={fetchDiagnosticAvailability}
            markRead={markStoryRead}
            handleStory={handleStory}
            requestDiagnostic={requestDiagnostic}
            cancelDiagnostic={cancelDiagnostic}
            onBack={() => setSelectedStoryId(null)}
            onOpenFact={(factId) => {
              setSelectedFactId(factId);
              setInitialFactFilters(null);
              setSelectedStoryId(null);
              setView('facts');
            }}
          />
        )}
        {view === 'facts' && (
          <FactQueryPage
            initialFactFilters={initialFactFilters}
            initialFactId={selectedFactId}
            loadFacts={fetchFacts}
            loadFactDetail={fetchFactDetail}
          />
        )}
        {view === 'collectors' && (
          <CollectorsPage
            loadCollectors={fetchCollectors}
            deleteCollector={deleteCollector}
            updateRawUpload={updateCollectorRawUpload}
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
