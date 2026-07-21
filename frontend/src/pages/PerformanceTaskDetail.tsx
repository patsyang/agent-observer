/** 性能观测 - 任务详情抽屉（点击 trace_id 后展开的 span 明细）。 */
import { X } from 'lucide-react';

import type { PerfContextEvent, PerfSpan, PerfTaskDetail } from '../api/types.performance';
import { formatDuration, formatNumber } from '../utils/numberFormat';
import { formatFullDateTime } from './dashboardLabels';
import {
  contextEventLabel,
  explainTaskError,
  isInterruptError,
  perfStatusBadgeClass,
  perfStatusLabel,
} from './perfLabels';

interface Props {
  traceId: string;
  detail: PerfTaskDetail | null;
  loading: boolean;
  error: boolean;
  onClose: () => void;
  /** 点击"查看会话"时跳转到该 fact 对应的会话详情。 */
  onOpenFact?: (factId: string) => void;
}

function spanTypeLabel(spanType: string): string {
  const labels: Record<string, string> = {
    llm_call: 'LLM 调用',
    tool_call: '工具调用',
    mcp_call: 'MCP 调用',
    task: '任务',
  };
  return labels[spanType] || spanType || '未知';
}

function severityBadgeClass(severity: string): string {
  if (severity === 'high') return 'badge red';
  if (severity === 'medium') return 'badge amber';
  return 'badge gray';
}

function severityLabel(severity: string): string {
  if (severity === 'high') return '高风险';
  if (severity === 'medium') return '中风险';
  if (severity === 'low') return '低风险';
  return severity || '未知';
}

export function PerformanceTaskDetail({ traceId, detail, loading, error, onClose, onOpenFact }: Props) {
  // P1-1: 元数据状态用 rolled-up task_error（与任务列表同口径），
  // 避免 task span ok 但子 span interrupted 时抽屉显示"失败"而列表显示"已中断"。
  const taskError = detail?.task_error || '';
  const isInterrupted = detail?.task_status === 'error' && isInterruptError(taskError);
  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside
        className="drawer perf-detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="任务详情"
        data-testid="perf-task-detail"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <span>任务详情</span>
            <h2>Trace</h2>
            <p><code>{traceId}</code></p>
            {detail && (
              <p>{formatFullDateTime(detail.started_at)} - {formatFullDateTime(detail.ended_at)}</p>
            )}
          </div>
          <div className="drawer-header-actions">
            <button className="ghost-button" onClick={onClose} type="button" aria-label="关闭任务详情">
              <X aria-hidden="true" size={16} />
            </button>
          </div>
        </header>

        <div className="perf-detail-drawer__body">
          {loading && <p>正在加载...</p>}
          {error && <p className="error-text">任务详情加载失败，请确认后端服务正常。</p>}
          {!loading && !error && !detail && <p>未找到该任务的明细数据。</p>}

          {detail && (
            <>
              <dl className="drawer-meta">
                <div><dt>Agent</dt><dd>{detail.agent_type || '-'}</dd></div>
                <div>
                  <dt>任务状态</dt>
                  <dd>
                    <span className={perfStatusBadgeClass(detail.task_status, taskError)}>
                      {perfStatusLabel(detail.task_status, taskError)}
                    </span>
                  </dd>
                </div>
                <div><dt>调用数</dt><dd>{formatNumber(detail.call_count)}</dd></div>
                <div><dt>会话</dt><dd>{detail.conversation_ref || '-'}</dd></div>
                <div><dt>Span 数</dt><dd>{formatNumber(detail.spans.length)}</dd></div>
              </dl>

              {detail.task && (
                <section className="drawer-section">
                  <h3>任务 Span（自身）</h3>
                  <dl className="drawer-meta">
                    <div><dt>耗时</dt><dd>{formatDuration(detail.task.duration_ms)}</dd></div>
                    <div>
                      <dt>状态</dt>
                      <dd>
                        <span className={perfStatusBadgeClass(detail.task.status, detail.task.error)}>
                          {perfStatusLabel(detail.task.status, detail.task.error)}
                        </span>
                      </dd>
                    </div>
                    {detail.task.error && (
                      <div style={{ gridColumn: '1 / -1' }}>
                        <dt>错误</dt>
                        <dd style={{ wordBreak: 'break-word' }}>
                          <code>{explainTaskError(detail.task.error)}</code>
                          {isInterrupted && (
                            <p className="hint" style={{ marginTop: 4, color: 'var(--warning-text, #8a6d3b)' }}>
                              该任务被用户主动中断，并非系统错误。中断前若已产生文件变更等操作，见下方"会话期间关键事件"。
                            </p>
                          )}
                        </dd>
                      </div>
                    )}
                  </dl>
                  {detail.task.status === 'ok' && detail.task_status === 'error' && (
                    <p className="hint" style={{ color: 'var(--warning-text, #8a6d3b)' }}>
                      任务 Span 自身状态为成功，但存在失败的子 Span，因此任务整体状态标记为
                      {perfStatusLabel(detail.task_status, taskError)}。
                      {isInterrupted && ' 该任务被用户主动中断，并非系统错误。'}
                      见下方"会话期间关键事件"了解中断前的上下文。
                    </p>
                  )}
                </section>
              )}

              {detail.context_events && detail.context_events.length > 0 && (
                <section className="drawer-section" data-testid="perf-context-events">
                  <h3>会话期间关键事件 ({formatNumber(detail.context_events.length)})</h3>
                  <p className="hint">
                    以下是该任务所在会话内的风险与错误事件，帮助理解失败时的上下文。点击"查看会话"可定位到具体调用。
                  </p>
                  <table className="responsive-table">
                    <thead>
                      <tr>
                        <th>时间</th>
                        <th>类型</th>
                        <th>严重度</th>
                        <th>描述</th>
                        {onOpenFact && <th>操作</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {detail.context_events.map((event: PerfContextEvent) => (
                        <tr key={event.fact_id} data-testid="perf-context-event-row">
                          <td data-label="时间">{formatFullDateTime(event.occurred_at)}</td>
                          <td data-label="类型">{contextEventLabel(event)}</td>
                          <td data-label="严重度">
                            <span className={severityBadgeClass(event.severity)}>
                              {severityLabel(event.severity)}
                            </span>
                          </td>
                          <td data-label="描述" style={{ wordBreak: 'break-word' }}>{event.summary || '-'}</td>
                          {onOpenFact && (
                            <td data-label="操作">
                              <button
                                className="link-button"
                                data-testid="perf-context-open-fact"
                                aria-label={`查看会话 ${event.fact_id}`}
                                onClick={() => onOpenFact(event.fact_id)}
                                type="button"
                              >
                                查看会话
                              </button>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}

              <section className="drawer-section">
                <h3>Span 明细 ({formatNumber(detail.spans.length)})</h3>
                {detail.spans.length >= 1000 && (
                  <p className="hint" style={{ color: 'var(--warning-text, #8a6d3b)' }}>
                    Span 数量达到 1000 条上限，可能还有更多未显示。
                  </p>
                )}
                <table className="responsive-table">
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>类型</th>
                      <th>名称</th>
                      <th title="Span 自身执行耗时（end - start）。单位 ms。">耗时</th>
                      <th title="TTFT（Time To First Token，首 token 延迟）：从请求发出到收到第一个 token 的耗时。单位 ms。仅 LLM 调用 span 有此指标，其他类型显示 —。">TTFT</th>
                      <th title="TPS（Tokens Per Second，每秒 token 数）：生成速度。单位 tokens/s。当前采集器暂未采集此指标，显示 —。">TPS</th>
                      <th>状态</th>
                      {onOpenFact && <th>操作</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {detail.spans.length === 0 ? (
                      <tr><td colSpan={onOpenFact ? 8 : 7}>该任务暂无 Span 数据。</td></tr>
                    ) : detail.spans.map((span: PerfSpan) => (
                      <tr key={span.signal_id} data-testid="perf-span-row">
                        <td data-label="时间">{formatFullDateTime(span.occurred_at)}</td>
                        <td data-label="类型">{spanTypeLabel(span.span_type)}</td>
                        <td data-label="名称">{span.tool_name || span.span_name || span.model || '-'}</td>
                        <td data-label="耗时">{formatDuration(span.duration_ms)}</td>
                        <td data-label="TTFT">{span.ttft_ms > 0 ? formatDuration(span.ttft_ms) : '—'}</td>
                        <td data-label="TPS">{span.tps > 0 ? span.tps.toFixed(1) : '—'}</td>
                        <td data-label="状态">
                          <span className={perfStatusBadgeClass(span.status, span.error)}>
                            {perfStatusLabel(span.status, span.error)}
                          </span>
                        </td>
                        {onOpenFact && (
                          <td data-label="操作">
                            {span.fact_id ? (
                              <button
                                className="link-button"
                                data-testid="perf-span-open-fact"
                                aria-label={`查看会话 ${span.fact_id}`}
                                onClick={() => onOpenFact(span.fact_id)}
                                type="button"
                              >
                                查看会话
                              </button>
                            ) : (
                              <span className="cell-muted">-</span>
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

