import type { ObservedFact } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { factTypeLabel, formatDateTime, localizedSummary } from './dashboardLabels';
import {
  eventTypeText,
  factSourceLabel,
  highlightSensitiveTerms,
  qualityText,
  rawStatusText,
} from './factQueryPresentation';

interface Props {
  facts: ObservedFact[];
  meta: { total: number; limit: number; offset: number };
  onInspect: (factId: string) => void;
  onPage: (offset: number) => void;
  selectedFactId: string | null;
}

export function FactTable({ facts, meta, onInspect, onPage, selectedFactId }: Props) {
  const start = meta.total === 0 ? 0 : meta.offset + 1;
  const end = Math.min(meta.offset + facts.length, meta.total);
  return (
    <div className="table-wrap">
      <div className="result-toolbar">
        <p className="result-note">
          共 {formatNumber(meta.total)} 条，第 {formatNumber(start)}-{formatNumber(end)} 条，每页 {formatNumber(meta.limit)} 条。
        </p>
        <div className="pagination">
          <button disabled={meta.offset === 0} onClick={() => onPage(Math.max(0, meta.offset - meta.limit))} type="button">
            上一页
          </button>
          <button disabled={end >= meta.total} onClick={() => onPage(meta.offset + meta.limit)} type="button">
            下一页
          </button>
        </div>
      </div>
      <table className="responsive-table">
        <thead>
          <tr>
            <th>序号</th>
            <th>观测到什么</th>
            <th>真实内容</th>
            <th>可信度</th>
            <th>来源 / 时间</th>
            <th>原文</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((fact, index) => (
            <FactRow
              absoluteIndex={meta.offset + index + 1}
              fact={fact}
              isSelected={fact.fact_id === selectedFactId}
              key={fact.fact_id}
              onInspect={onInspect}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FactRow({
  absoluteIndex,
  fact,
  isSelected,
  onInspect
}: {
  absoluteIndex: number;
  fact: ObservedFact;
  isSelected: boolean;
  onInspect: (factId: string) => void;
}) {
  return (
    <tr aria-selected={isSelected ? 'true' : 'false'} className={isSelected ? 'selected-row' : ''}>
      <td data-label="序号">{formatNumber(absoluteIndex)}</td>
      <td data-label="观测到什么">
        <strong>{factTypeLabel(fact.category || fact.fact_type)}</strong>
        <small>{eventTypeText(fact.source_event_type)}</small>
      </td>
      <td data-label="真实内容">
        <span className="content-preview" title={fact.content_preview || localizedSummary(fact.summary)}>
          {highlightSensitiveTerms(fact.content_preview || localizedSummary(fact.summary))}
        </span>
        {fact.content_preview && fact.content_preview !== fact.summary && <small>{localizedSummary(fact.summary)}</small>}
      </td>
      <td data-label="可信度">{qualityText(fact.quality)}</td>
      <td data-label="来源 / 时间">
        {factSourceLabel(fact)}
        <small>{formatDateTime(fact.occurred_at)}</small>
      </td>
      <td data-label="原文">
        <span className={`badge ${fact.raw_available ? 'green' : 'gray'}`}>{rawStatusText(fact)}</span>
      </td>
      <td data-label="操作">
        <button className="compact-button" onClick={() => onInspect(fact.fact_id)} aria-label={`查看 ${fact.fact_id}`} type="button">
          查看
        </button>
      </td>
    </tr>
  );
}
