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
  fetchRecentAudit,
  fetchRiskSummary,
  fetchStories,
  fetchStoryDetail,
  fetchUsageSummary,
  handleStory,
  markStoryRead,
  requestEnrichment,
  updatePolicy
} from './api/client';
import { AccessConfigDrawer } from './components/AccessConfigDrawer';
import { CollectorsPage } from './pages/CollectorsPage';
import { ConversationQueryPage } from './pages/ConversationQueryPage';
import { DashboardPage } from './pages/DashboardPage';
import { ObservationStoryDetailPage } from './pages/ObservationStoryDetailPage';

type View = 'dashboard' | 'collectors' | 'conversations';

const navItems: Array<{ view: View; label: string; desc: string; icon: typeof LayoutDashboard }> = [
  { view: 'dashboard', label: '观测总览', desc: '信号与用量', icon: LayoutDashboard },
  { view: 'conversations', label: '会话查询', desc: '输入与响应', icon: MessagesSquare },
  { view: 'collectors', label: '采集器', desc: '状态与策略', icon: Radio }
];

export function App() {
  const [view, setView] = useState<View>('dashboard');
  const [selectedStoryId, setSelectedStoryId] = useState<string | null>(null);
  const [selectedFactId, setSelectedFactId] = useState<string | null>(null);
  const [returnStoryId, setReturnStoryId] = useState<string | null>(null);
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
                setReturnStoryId(null);
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
        <button className="primary full-width" onClick={() => setDrawerOpen(true)}>
          <ActivitySquare aria-hidden="true" size={16} />
          接入配置
        </button>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{view === 'dashboard' ? '观测总览' : view === 'conversations' ? '会话查询' : '采集器'}</h1>
            <p>围绕信号、会话输入输出和 collector 接入状态进行日常排查。</p>
          </div>
        </header>
        {view === 'dashboard' && selectedStoryId === null && (
          <DashboardPage
            loadDashboardSummary={fetchDashboardSummary}
            loadStories={fetchStories}
            loadUsageSummary={fetchUsageSummary}
            loadRiskSummary={fetchRiskSummary}
            onOpenStory={setSelectedStoryId}
          />
        )}
        {view === 'dashboard' && selectedStoryId !== null && (
          <ObservationStoryDetailPage
            storyId={selectedStoryId}
            loadStoryDetail={fetchStoryDetail}
            loadEnrichmentAvailability={fetchEnrichmentAvailability}
            markRead={markStoryRead}
            handleStory={handleStory}
            requestEnrichment={requestEnrichment}
            cancelEnrichment={cancelEnrichment}
            onBack={() => setSelectedStoryId(null)}
            onOpenFact={(factId) => {
              setSelectedFactId(factId);
              setReturnStoryId(selectedStoryId);
              setSelectedStoryId(null);
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
            onBack={returnStoryId ? () => {
              setSelectedFactId(null);
              setSelectedStoryId(returnStoryId);
              setReturnStoryId(null);
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
