import type { RefObject } from 'react';

import type { FactDetail } from '../api/types';
import {
  eventTypeText,
  highlightSensitiveTerms,
  objectTypeLabel,
  rawStatusText,
  shortHash,
  sourceText
} from './factQueryPresentation';

interface Props {
  detail: FactDetail;
  factIndexLabel: string;
  panelRef: RefObject<HTMLElement | null>;
}

export function FactDetailPanel({ detail, factIndexLabel, panelRef }: Props) {
  const promptText = extractPromptText(detail);
  const projectionRows = readableProjectionRows(detail.evidence_projection.projection_json);
  const riskObject = riskObjectFromProjection(detail.evidence_projection.projection_json);

  return (
    <aside className="detail-panel fact-detail-side" ref={panelRef} aria-label="证据详情">
      <div className="detail-panel__heading">
        <div>
          <h3>证据详情</h3>
          <p>
            {factIndexLabel} / {detail.fact.fact_id} / {eventTypeText(String(detail.source_specific_json.codex_event_type ?? 'unknown'))}
          </p>
        </div>
        <span className={`badge ${detail.fact.raw_available ? 'green' : 'gray'}`}>{rawStatusText(detail.fact)}</span>
      </div>
      {riskObject && (
        <div className="risk-object-strip risk-object-strip--detail">
          <span>敏感对象</span>
          <strong>{riskObject}</strong>
        </div>
      )}
      <dl className="evidence-detail-grid">
        <div>
          <dt>来源事件</dt>
          <dd>{eventTypeText(String(detail.source_specific_json.codex_event_type ?? 'unknown'))}</dd>
        </div>
        <div>
          <dt>来源位置</dt>
          <dd>{detail.fact.source_label || sourceText(detail.fact.source)}</dd>
        </div>
        <div>
          <dt>证据范围</dt>
          <dd title={detail.evidence_projection.span}>{detail.evidence_projection.span}</dd>
        </div>
        <div>
          <dt>材料指纹</dt>
          <dd title={detail.evidence_projection.raw_hash}>{shortHash(detail.evidence_projection.raw_hash)}</dd>
        </div>
      </dl>
      <section className="projection-section" aria-label="结构化字段">
        <h4>结构化字段</h4>
        <table>
          <tbody>
            {projectionRows.map((row) => (
              <tr key={row.label}>
                <th>{row.label}</th>
                <td>{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {promptText && (
        <section className="raw-block" aria-label="原始 Prompt">
          <h4>原始 Prompt</h4>
          <pre>{highlightSensitiveTerms(promptText)}</pre>
        </section>
      )}
      <section className="raw-block raw-block--last" aria-label="原文证据">
        <h4>原文证据</h4>
        {detail.evidence_projection.raw_content ? (
          <pre>{highlightSensitiveTerms(detail.evidence_projection.raw_content)}</pre>
        ) : (
          <p>未上传原文，本条只能查看摘要、字段和值。</p>
        )}
      </section>
    </aside>
  );
}

export function EmptyDetailPanel() {
  return (
    <aside className="detail-panel muted-detail fact-detail-side" aria-label="证据详情">
      <h3>证据详情</h3>
      <p>点击列表中的“查看”，右侧会显示对应事实的真实内容、来源位置、原始 Prompt 和完整原文。</p>
    </aside>
  );
}

function extractPromptText(detail: FactDetail): string {
  const projectionValue = detail.evidence_projection.projection_json.prompt_text;
  if (typeof projectionValue === 'string') return projectionValue;
  return '';
}

function readableProjectionRows(projection: Record<string, unknown>): Array<{ label: string; value: string }> {
  const rows = Object.entries(projection).map(([key, value]) => ({
    label: projectionLabel(key),
    value: projectionValue(key, value),
  }));
  return rows.length ? rows : [{ label: '字段', value: '无结构化字段' }];
}

function projectionLabel(key: string): string {
  const labels: Record<string, string> = {
    object_type: '对象类型',
    category_count: '命中线索数',
    sensitive_categories: '命中线索',
    role: '消息角色',
    content_length: '内容长度',
    prompt_text: 'Prompt 摘要',
    raw_content_uploaded: '原文状态',
    tool_name: '工具',
    payload_type: '事件类型',
    command_category: '命令类别',
    exit_code: '退出码',
  };
  return labels[key] ?? key;
}

function projectionValue(key: string, value: unknown): string {
  if (key === 'object_type' && typeof value === 'string') return objectTypeLabel(value);
  if (Array.isArray(value)) return value.map(String).join('、');
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (value === null || value === undefined || value === '') return '无';
  return String(value);
}

function riskObjectFromProjection(projection: Record<string, unknown>): string | null {
  const value = projection.object_type;
  return typeof value === 'string' ? objectTypeLabel(value) : null;
}
