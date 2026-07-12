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
  }) => Promise<McpCallsResponse>;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: McpCallsResponse };

const PAGE_SIZE = 20;

export function McpObservationPage({ loadMcpCalls }: Props) {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [server, setServer] = useState('');
  const [riskOnly, setRiskOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    loadMcpCalls({
      page,
      page_size: PAGE_SIZE,
      server: server || undefined,
      risk_only: riskOnly || undefined,
    })
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', data });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, [loadMcpCalls, page, server, riskOnly]);

  if (state.status === 'loading') {
    return (
      <section className="panel" data-testid="mcp-page">
        <h2>MCP 工具调用观测</h2>
        <p>正在加载 MCP 调用记录。</p>
      </section>
    );
  }
  if (state.status === 'error') {
    return (
      <section className="panel" data-testid="mcp-page">
        <h2>MCP 工具调用观测</h2>
        <p>MCP 调用数据不可用。请确认后端服务正常。</p>
      </section>
    );
  }

  const { items, summary, total } = state.data;
  const hasMore = page * PAGE_SIZE < total;
  const resetPage = () => setPage(1);

  return (
    <section className="panel" data-testid="mcp-page">
      <h2>MCP 工具调用观测</h2>
      <p className="panel-intro">审计 MCP 工具调用的耗时、错误与关联风险信号。</p>

      <section className="metrics" aria-label="MCP 汇总">
        <div className="metric" data-testid="mcp-summary-servers">
          <span>Servers</span>
          <strong>{formatNumber(summary.servers.length)}</strong>
          <small>已接入服务器</small>
        </div>
        <div className="metric" data-testid="mcp-summary-total">
          <span>调用总数</span>
          <strong>{formatNumber(summary.total_calls)}</strong>
          <small>窗口内调用</small>
        </div>
        <div className="metric" data-testid="mcp-summary-errors">
          <span>错误数</span>
          <strong>{formatNumber(summary.error_calls)}</strong>
          <small>失败调用</small>
        </div>
        <div className="metric" data-testid="mcp-summary-risks">
          <span>风险数</span>
          <strong>{formatNumber(summary.risk_calls)}</strong>
          <small>命中风险信号</small>
        </div>
      </section>

      <section className="context-bar">
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
      </section>

      <table className="responsive-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>Server</th>
            <th>Tool</th>
            <th>耗时</th>
            <th>错误</th>
            <th>参数键</th>
            <th>风险信号</th>
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
                <td data-label="耗时">{formatNumber(item.mcp_duration_ms)} ms</td>
                <td data-label="错误">{item.mcp_is_error ? '是' : '否'}</td>
                <td data-label="参数键">{formatNumber(item.argument_keys.length)}</td>
                <td data-label="风险信号">{formatNumber(item.risk_signals.length)}</td>
              </tr>
              {expandedId === item.fact_id && (
                <tr data-testid="mcp-call-detail">
                  <td colSpan={7}>
                    <div className="source-list">
                      <strong>参数键：</strong>
                      {item.argument_keys.map((key) => (
                        <span className="source-pill" key={key}>{key}</span>
                      ))}
                    </div>
                    {item.risk_signals.length > 0 && (
                      <div className="source-list">
                        <strong>风险信号：</strong>
                        {item.risk_signals.map((signal) => (
                          <span className="source-pill" key={signal}>{signal}</span>
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

      <div className="list-footer">
        <button disabled={page <= 1} onClick={() => setPage(page - 1)} type="button">上一页</button>
        <span>第 {formatNumber(page)} 页 / 共 {formatNumber(Math.max(1, Math.ceil(total / PAGE_SIZE)))} 页</span>
        <button disabled={!hasMore} onClick={() => setPage(page + 1)} type="button">下一页</button>
      </div>
    </section>
  );
}
