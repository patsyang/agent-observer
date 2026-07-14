import { Fragment, useEffect, useState } from 'react';

import type { McpCallsResponse } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { formatFullDateTime } from './dashboardLabels';

interface Props {
  loadMcpCalls: (params: {
    page?: number;
    page_size?: number;
    server?: string;
    risk_only?: boolean;
    error_only?: boolean;
  }) => Promise<McpCallsResponse>;
}

type LoadState =
  | { status: 'error' }
  | { status: 'ready'; data: McpCallsResponse; loading: boolean };

const PAGE_SIZE = 20;

const emptyData: McpCallsResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: PAGE_SIZE,
  summary: { servers: [], total_calls: 0, error_calls: 0, risk_calls: 0 },
};

export function McpObservationPage({ loadMcpCalls }: Props) {
  const [state, setState] = useState<LoadState>({
    status: 'ready',
    data: emptyData,
    loading: true,
  });
  const [server, setServer] = useState('');
  const [riskOnly, setRiskOnly] = useState(false);
  const [errorOnly, setErrorOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState((c) => (c.status === 'ready' ? { ...c, loading: true } : c));
    loadMcpCalls({
      page,
      page_size: PAGE_SIZE,
      server: server || undefined,
      risk_only: riskOnly || undefined,
      error_only: errorOnly || undefined,
    })
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data, loading: false });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [loadMcpCalls, page, server, riskOnly, errorOnly]);

  if (state.status === 'error') {
    return (
      <section className="panel" data-testid="mcp-page">
        <p>MCP 调用数据不可用。请确认后端服务正常。</p>
      </section>
    );
  }

  const { items, summary, total } = state.data;
  const hasMore = page * PAGE_SIZE < total;
  const resetPage = () => setPage(1);
  const showPlaceholder = state.loading && items.length === 0;

  return (
    <section className="panel" data-testid="mcp-page">
      <section className="metrics" aria-label="MCP 汇总">
        <div className="metric" data-testid="mcp-summary-servers">
          <span>Servers</span>
          <strong>{showPlaceholder ? '—' : formatNumber(summary.servers.length)}</strong>
          <small>已接入服务器</small>
        </div>
        <div className="metric" data-testid="mcp-summary-total">
          <span>调用总数</span>
          <strong>{showPlaceholder ? '—' : formatNumber(summary.total_calls)}</strong>
          <small>窗口内调用</small>
        </div>
        <div className="metric" data-testid="mcp-summary-errors">
          <span>错误数</span>
          <strong>{showPlaceholder ? '—' : formatNumber(summary.error_calls)}</strong>
          <small>失败调用</small>
        </div>
        <div className="metric" data-testid="mcp-summary-risks">
          <span>风险数</span>
          <strong>{showPlaceholder ? '—' : formatNumber(summary.risk_calls)}</strong>
          <small>命中风险信号</small>
        </div>
      </section>

      <section className="filter-bar">
        <label className="compact-filter">
          MCP Server
          <select aria-label="MCP Server" onChange={(e) => { setServer(e.target.value); resetPage(); }} value={server}>
            <option value="">全部</option>
            {summary.servers.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </label>
        <label className="compact-filter">
          <input
            type="checkbox"
            checked={riskOnly}
            onChange={(e) => { setRiskOnly(e.target.checked); resetPage(); }}
          />
          仅看风险
        </label>
        <label className="compact-filter">
          <input
            type="checkbox"
            checked={errorOnly}
            onChange={(e) => { setErrorOnly(e.target.checked); resetPage(); }}
          />
          仅看错误
        </label>
      </section>

      <table className="responsive-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>Server</th>
            <th>Tool</th>
            <th>操作摘要</th>
            <th>耗时</th>
            <th>错误</th>
            <th>风险</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <Fragment key={item.fact_id}>
              <tr
                data-testid="mcp-call-row"
                onClick={() => setExpandedId(expandedId === item.fact_id ? null : item.fact_id)}
              >
                <td data-label="时间">{formatFullDateTime(item.occurred_at)}</td>
                <td data-label="Server">{item.mcp_server}</td>
                <td data-label="Tool">{item.mcp_tool}</td>
                <td data-label="操作摘要">{item.mcp_args_summary || '-'}</td>
                <td data-label="耗时">{formatNumber(item.mcp_duration_ms)} ms</td>
                <td data-label="错误">{item.mcp_is_error ? '是' : '否'}</td>
                <td data-label="风险">{formatNumber(item.risk_signals.length)}</td>
              </tr>
              {expandedId === item.fact_id && (
                <tr data-testid="mcp-call-detail">
                  <td colSpan={7}>
                    {item.arguments.length > 0 && (
                      <div className="mcp-detail-section">
                        <strong>参数</strong>
                        {item.arguments.map((arg) => (
                          <div className="mcp-arg" key={arg.key}>
                            <span className="mcp-arg-key">{arg.key}</span>
                            <pre className="mcp-arg-value">{arg.value}</pre>
                          </div>
                        ))}
                      </div>
                    )}
                    {item.result_text && (
                      <div className="mcp-detail-section">
                        <strong>结果</strong>
                        <pre className="mcp-result-text">{item.result_text}</pre>
                      </div>
                    )}
                    <div className="mcp-detail-section">
                      <strong>会话</strong>
                      <span className="mcp-conv-ref">{item.conversation_ref}</span>
                    </div>
                    {item.risk_signals.length > 0 && (
                      <div className="mcp-detail-section">
                        <strong>风险信号</strong>
                        {item.risk_signals.map((signal, idx) => (
                          <div className="mcp-risk-row" key={idx}>
                            <span className={`severity-badge severity-${signal.severity}`}>{signal.severity}</span>
                            <span className="mcp-risk-type">{signal.risk_type}</span>
                            <span className="mcp-risk-object">对象: {signal.object_type}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>

      <div className="pagination">
        <button disabled={page <= 1} onClick={() => setPage(page - 1)} type="button">上一页</button>
        <span>第 {formatNumber(page)} 页 / 共 {formatNumber(Math.max(1, Math.ceil(total / PAGE_SIZE)))} 页</span>
        <button disabled={!hasMore} onClick={() => setPage(page + 1)} type="button">下一页</button>
      </div>
    </section>
  );
}
