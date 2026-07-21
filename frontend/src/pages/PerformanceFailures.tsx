/** 性能观测 - 失败时间线子组件（status=error 的 perf_signals 列表）。 */
import { formatDuration, formatNumber } from '../utils/numberFormat';
import { formatFullDateTime } from './dashboardLabels';
import type { PerfFailureRow } from '../api/types.performance';
import { explainTaskError, isInterruptError } from './perfLabels';

const FAILURE_LIMIT = 200;

interface Props {
  failures: PerfFailureRow[];
  loading: boolean;
  error?: boolean;
  /** 点击"查看会话"时跳转到该 fact 对应的会话详情。 */
  onOpenFact?: (factId: string) => void;
}

function spanTypeLabel(spanType: string): string {
  if (spanType === 'llm_call') return 'LLM 调用';
  if (spanType === 'tool_call') return '工具调用';
  if (spanType === 'mcp_call') return 'MCP 调用';
  if (spanType === 'task') return '任务';
  return spanType || '未知';
}

export function PerformanceFailures({ failures, loading, error, onOpenFact }: Props) {
  const showPlaceholder = loading && failures.length === 0;
  // R2-X6: 后端 limit 200，达到上限时提示"最近 N 条"而非"共 N 条"
  const atLimit = failures.length >= FAILURE_LIMIT;
  const countLabel = atLimit ? `最近 ${formatNumber(failures.length)} 条` : `共 ${formatNumber(failures.length)} 条`;
  const showAction = Boolean(onOpenFact);
  // 区分"真失败"与"用户中断"——中断不属于系统错误，标签弱化
  const interruptCount = failures.filter((f) => isInterruptError(f.error)).length;
  const realFailureCount = failures.length - interruptCount;
  const headerLabel = realFailureCount > 0 && interruptCount > 0
    ? `${countLabel}（失败 ${formatNumber(realFailureCount)} / 中断 ${formatNumber(interruptCount)}）`
    : countLabel;

  return (
    <section className="panel" aria-label="失败时间线">
      <div className="panel-header">
        <h2>失败时间线</h2>
        <span className="badge amber">{headerLabel}</span>
      </div>
      <table className="responsive-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>Trace</th>
            <th>类型</th>
            <th>名称 / 工具</th>
            <th>耗时</th>
            <th>错误信息</th>
            <th>分类</th>
            <th>Agent</th>
            {showAction && <th>操作</th>}
          </tr>
        </thead>
        <tbody>
          {error && failures.length === 0 ? (
            <tr><td colSpan={showAction ? 9 : 8} className="error-text">失败时间线加载失败，请确认后端服务正常。</td></tr>
          ) : showPlaceholder ? (
            <tr><td colSpan={showAction ? 9 : 8}><span className="loading-inline">加载中</span></td></tr>
          ) : failures.length === 0 ? (
            <tr><td colSpan={showAction ? 9 : 8}>当前窗口内没有失败记录。</td></tr>
          ) : failures.map((row) => {
            const interrupted = isInterruptError(row.error);
            return (
              <tr key={row.signal_id} data-testid="perf-failure-row">
                <td data-label="时间">{formatFullDateTime(row.occurred_at)}</td>
                <td data-label="Trace"><code>{row.trace_id || '-'}</code></td>
                <td data-label="类型">{spanTypeLabel(row.span_type)}</td>
                <td data-label="名称 / 工具">{row.tool_name || row.span_name || '-'}</td>
                <td data-label="耗时">{formatDuration(row.duration_ms)}</td>
                <td data-label="错误信息" style={{ maxWidth: 360, wordBreak: 'break-word' }}>
                  <code>{explainTaskError(row.error) || '-'}</code>
                </td>
                <td data-label="分类">
                  <span className={interrupted ? 'badge gray' : 'badge amber'}>
                    {interrupted ? '已中断' : '失败'}
                  </span>
                </td>
                <td data-label="Agent">{row.agent_type || '-'}</td>
                {showAction && (
                  <td data-label="操作">
                    {row.fact_id ? (
                      <button
                        className="link-button"
                        data-testid="perf-failure-open-fact"
                        aria-label={`查看会话 ${row.fact_id}`}
                        onClick={() => onOpenFact?.(row.fact_id)}
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
            );
          })}
        </tbody>
      </table>
      {atLimit && <p className="hint">仅显示最近 {formatNumber(FAILURE_LIMIT)} 条失败记录。</p>}
    </section>
  );
}
