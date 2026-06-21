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
        <thead>
          <tr>
            <th>序号</th>
            <th>时间戳</th>
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
              <td data-label="提交 Prompt"><span className="content-preview">{row.prompt_preview || '暂无 Prompt'}</span></td>
              <td data-label="响应内容"><span className="content-preview">{row.response_preview || '暂无响应'}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
