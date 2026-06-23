import type { ConversationSummary } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { formatDateTime } from './dashboardLabels';

export function ConversationTable({
  meta,
  onOpen,
  onPage,
  rows,
}: {
  meta: { total: number; page: number; page_size: number; has_more: boolean };
  onOpen: (conversationRef: string) => void;
  onPage: (page: number) => void;
  rows: ConversationSummary[];
}) {
  return (
    <div className="table-wrap">
      <div className="result-toolbar">
        <p className="result-note">共 {formatNumber(meta.total)} 个会话</p>
        <div className="pagination">
          <button disabled={meta.page <= 1} onClick={() => onPage(meta.page - 1)} type="button">上一页</button>
          <span>第 {formatNumber(meta.page)} 页</span>
          <button disabled={!meta.has_more} onClick={() => onPage(meta.page + 1)} type="button">下一页</button>
        </div>
      </div>
      <table className="responsive-table conversation-table">
        <colgroup>
          <col className="conversation-table__index" />
          <col className="conversation-table__time" />
          <col className="conversation-table__workspace" />
          <col className="conversation-table__source" />
          <col className="conversation-table__session" />
          <col className="conversation-table__prompt" />
          <col className="conversation-table__response" />
        </colgroup>
        <thead>
          <tr>
            <th>序号</th>
            <th>时间戳</th>
            <th>工作区</th>
            <th>来源</th>
            <th>会话名</th>
            <th>提交 Prompt</th>
            <th>响应内容</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              className="clickable-row"
              data-conversation-ref={row.conversation_ref}
              data-testid="conversation-row"
              key={row.conversation_ref}
              onClick={() => onOpen(row.conversation_ref)}
              tabIndex={0}
            >
              <td data-label="序号">{formatNumber((meta.page - 1) * meta.page_size + index + 1)}</td>
              <td data-label="时间戳">{formatDateTime(row.last_event_at)}</td>
              <td data-label="工作区">
                <span className="content-preview" title={row.workspace.workspace_path}>
                  {workspaceLabel(row)}
                </span>
              </td>
              <td data-label="来源">{sourceLabel(row)}</td>
              <td data-label="会话名"><span className="content-preview">{row.session_title || row.session_ref || '未知会话'}</span></td>
              <td data-label="提交 Prompt"><span className="content-preview">{row.prompt_preview || '暂无 Prompt'}</span></td>
              <td data-label="响应内容"><span className="content-preview">{row.response_preview || '暂无响应'}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function sourceLabel(row: ConversationSummary): string {
  if (row.agent_type === 'codex') return 'Codex';
  if (row.agent_type === 'workbuddy') return 'WorkBuddy';
  return row.agent_type || '未知';
}

function workspaceLabel(row: ConversationSummary): string {
  return row.workspace.workspace_label || basename(row.workspace.workspace_path) || '工作区未知';
}

function basename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
  return parts.at(-1) ?? '';
}
