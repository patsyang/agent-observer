/** 性能观测 - 任务列表子组件（按 trace_id 分组的任务表格 + 分页）。 */
import { formatDuration, formatNumber } from '../utils/numberFormat';
import { formatFullDateTime } from './dashboardLabels';
import type { PerfTaskRow, PerfTasksResponse } from '../api/types.performance';
import { perfStatusBadgeClass, perfStatusLabel } from './perfLabels';

const PAGE_SIZE = 20;

const emptyData: PerfTasksResponse = {
  window: '24h',
  page: 1,
  page_size: PAGE_SIZE,
  total: 0,
  tasks: [],
};

interface Props {
  data: PerfTasksResponse | null;
  loading: boolean;
  error?: boolean;
  page: number;
  onPageChange: (page: number) => void;
  onTraceClick?: (traceId: string) => void;
  /** 点击"查看会话"时跳转到该 fact 对应的会话详情。 */
  onOpenFact?: (factId: string) => void;
}

export function PerformanceTaskList({ data, loading, error, page, onPageChange, onTraceClick, onOpenFact }: Props) {
  const current = data ?? emptyData;
  const { tasks, total } = current;
  const hasMore = page * PAGE_SIZE < total;
  const showPlaceholder = loading && tasks.length === 0;
  const showAction = Boolean(onOpenFact);

  return (
    <section className="panel" aria-label="任务列表">
      <div className="panel-header">
        <h2>任务列表</h2>
        <span className="badge gray">共 {formatNumber(total)} 个任务</span>
      </div>
      <table className="responsive-table">
        <thead>
          <tr>
            <th>开始时间</th>
            <th>Trace ID</th>
            <th>Agent</th>
            <th>调用数</th>
            <th>LLM / 工具</th>
            <th title="任务总耗时（含 LLM 调用、工具调用、用户等待时间），非纯 LLM 耗时。">任务耗时</th>
            <th>状态</th>
            {showAction && <th>操作</th>}
          </tr>
        </thead>
        <tbody>
          {error && tasks.length === 0 ? (
            <tr><td colSpan={showAction ? 8 : 7} className="error-text">任务列表加载失败，请确认后端服务正常。</td></tr>
          ) : showPlaceholder ? (
            <tr><td colSpan={showAction ? 8 : 7}><span className="loading-inline">加载中</span></td></tr>
          ) : tasks.length === 0 ? (
            <tr><td colSpan={showAction ? 8 : 7}>当前窗口内没有任务记录。</td></tr>
          ) : tasks.map((task: PerfTaskRow) => (
            <tr key={task.trace_id} data-testid="perf-task-row">
              <td data-label="开始时间">{formatFullDateTime(task.started_at)}</td>
              <td data-label="Trace ID">
                {onTraceClick ? (
                  <button className="link-button" onClick={() => onTraceClick(task.trace_id)} type="button" data-testid="perf-trace-link">
                    <code>{task.trace_id}</code>
                  </button>
                ) : (
                  <code>{task.trace_id}</code>
                )}
              </td>
              <td data-label="Agent">{task.agent_type || '-'}</td>
              <td data-label="调用数">{formatNumber(task.call_count)}</td>
              <td data-label="LLM / 工具">{formatNumber(task.llm_call_count)} / {formatNumber(task.tool_call_count)}</td>
              <td data-label="任务耗时">{task.task_duration_ms ? formatDuration(task.task_duration_ms) : '—'}</td>
              <td data-label="状态">
                <span className={perfStatusBadgeClass(task.task_status, task.task_error)}>
                  {perfStatusLabel(task.task_status, task.task_error)}
                </span>
              </td>
              {showAction && (
                <td data-label="操作">
                  {task.fact_id ? (
                    <button
                      className="link-button"
                      data-testid="perf-task-open-fact"
                      aria-label={`查看会话 ${task.fact_id}`}
                      onClick={() => onOpenFact?.(task.fact_id)}
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
      <div className="pagination">
        <button disabled={page <= 1} onClick={() => onPageChange(page - 1)} type="button">上一页</button>
        <span>第 {formatNumber(page)} 页 / 共 {formatNumber(Math.max(1, Math.ceil(total / PAGE_SIZE)))} 页</span>
        <button disabled={!hasMore} onClick={() => onPageChange(page + 1)} type="button">下一页</button>
      </div>
    </section>
  );
}
