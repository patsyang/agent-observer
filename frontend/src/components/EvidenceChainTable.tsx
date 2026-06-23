import type { SignalEvidenceItem } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { factTypeLabel, formatDateTime } from '../pages/dashboardLabels';

interface Props {
  entries: SignalEvidenceItem[];
  onOpenFact?: (factId: string) => void;
}

const MAX_VISIBLE_EVIDENCE = 20;

export function EvidenceChainTable({ entries, onOpenFact }: Props) {
  if (entries.length === 0) {
    return <p data-testid="empty-evidence-chain">暂无命中内容。请确认采集器已上报结构化观测。</p>;
  }
  const orderedEntries = [...entries].sort((left, right) => {
    const timeCompare = (right.occurred_at || '').localeCompare(left.occurred_at || '');
    return timeCompare || right.evidence_ref.localeCompare(left.evidence_ref);
  });
  const visibleEntries = orderedEntries.slice(0, MAX_VISIBLE_EVIDENCE);

  return (
    <div className="evidence-table-wrap" data-testid="evidence-chain-table">
      {entries.length > visibleEntries.length && (
        <p className="result-note">
          该信号关联 {formatNumber(entries.length)} 条命中内容，当前按时间倒序展示前 {formatNumber(visibleEntries.length)} 条；完整排查请进入会话查询按时间和关键字过滤。
        </p>
      )}
      <table className="evidence-table responsive-table">
        <thead>
          <tr>
            <th>序号</th>
            <th>时间</th>
            <th>命中内容</th>
            <th>类型 / 来源</th>
            <th>可信度 / 原文</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {visibleEntries.map((entry, index) => (
            <tr data-evidence-ref={entry.evidence_ref} data-testid="evidence-row" key={entry.evidence_ref}>
              <td data-label="序号">{formatNumber(index + 1)}</td>
              <td data-label="时间">{formatDateTime(entry.occurred_at)}</td>
              <td data-label="命中内容">
                <span className="content-preview" title={entry.content_preview || summaryText(entry.summary)}>
                  {entry.content_preview || summaryText(entry.summary)}
                </span>
                {entry.sensitive_categories?.length ? (
                  <div className="evidence-tags" aria-label="风险对象">
                    {typeof entry.risk_category_count === 'number' && (
                      <span className="badge gray">命中 {formatNumber(entry.risk_category_count)} 类线索</span>
                    )}
                    {entry.sensitive_categories.slice(0, 3).map((category) => (
                      <span className="badge amber" key={category}>命中 {category}</span>
                    ))}
                  </div>
                ) : null}
                <small title={entry.evidence_ref}>{technicalRefLabel(entry)}</small>
              </td>
              <td data-label="类型 / 来源">
                <strong>{evidenceTypeLabel(entry)}</strong>
                <small>{sourceTypeText(entry)}</small>
              </td>
              <td data-label="可信度 / 原文">
                <span className={`badge ${qualityClass(entry.quality)}`}>{qualityLabel(entry.quality)}</span>
                <small className={entry.raw_available ? 'raw-state raw-state--on' : 'raw-state'}>
                  {rawStatusLabel(entry.raw_available, entry.raw_status)}
                </small>
              </td>
              <td data-label="操作">
                {entry.fact_id && onOpenFact ? (
                  <button className="compact-button" data-testid="open-fact-conversation" type="button" onClick={() => onOpenFact(entry.fact_id as string)}>
                    查看会话
                  </button>
                ) : (
                  <span className="muted-inline">无需跳转</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function evidenceTypeLabel(entry: SignalEvidenceItem): string {
  const normalized = entry.category.toLowerCase();
  if (normalized === 'tool_execution_failure') return '工具执行失败';
  if (normalized === 'tool_execution_timeout') return '工具执行超时';
  if (normalized === 'workflow_step_failure') return 'Workflow 失败';
  if (normalized === 'workflow_step_timeout') return 'Workflow 超时';
  if (normalized === 'file_change') return '文件变更';
  if (normalized === 'destructive_operation') return '破坏性操作';
  if (normalized === 'sensitive_content_exposure') return '敏感内容暴露';
  if (normalized === 'agent_prompt') return '用户 Prompt';
  if (normalized === 'agent_response') return 'Agent 消息';
  if (normalized === 'agent_reasoning') return '推理片段';
  if (normalized === 'enrichment_result') return '补证结果';
  if (normalized === 'collector_status') return '采集器状态';
  if (entry.summary.includes('collector')) return '采集器状态';
  return factTypeLabel(entry.fact_type || entry.category);
}

function summaryText(summary: string): string {
  const replacements: Record<string, string> = {
    已生成错误指纹: '已记录错误指纹，可用于识别同类错误复发',
    'Command failed': '工具执行失败，已记录结构化错误结果',
    'Configuration touched': '检测到配置对象触达，需要结合上下文判断是否符合预期',
  };
  if (replacements[summary]) return replacements[summary];
  const codexError = summary.match(/^Codex function_call_output 在 response_item 阶段失败，exit_code=(\d+)，已生成[^，。]*错误(?:签名|指纹)。$/);
  if (codexError) {
    return `Codex 工具执行结果在响应记录阶段失败，退出码 ${codexError[1]}；已记录错误指纹，可用于识别同类错误复发。`;
  }
  return summary
    .replace('function_call_output', '工具执行结果')
    .replace('response_item', '响应记录')
    .replace('exit_code=', '退出码 ')
    .replace(/已生成[^，。]*错误签名/g, '已记录错误指纹，可用于识别同类错误复发')
    .replace('已生成错误指纹', '已记录错误指纹，可用于识别同类错误复发');
}

function sourceTypeText(entry: SignalEvidenceItem): string {
  const event = eventTypeText(entry.source_event_type);
  const source = entry.source_label || sourceLabelFromRef(entry.evidence_ref);
  return `${source} · ${event}`;
}

function eventTypeText(value?: string): string {
  const labels: Record<string, string> = {
    message: '消息事件',
    user_message: '用户消息',
    agent_message: '模型消息',
    reasoning: '推理事件',
    function_call: '工具调用',
    function_call_output: '工具结果',
    tool_result: '工具结果',
    usage_summary: '用量汇总',
    enrichment_result: '补证结果',
    unknown: '未知事件',
  };
  return labels[value || 'unknown'] ?? value ?? '未知事件';
}

function sourceLabelFromRef(evidenceRef: string): string {
  if (evidenceRef.startsWith('enrichment-result-')) return '本机补证';
  if (evidenceRef.startsWith('proj-')) return '本机采集器';
  return '结构化观测库';
}

function qualityLabel(quality: string): string {
  const labels: Record<string, string> = {
    high: '高可信',
    low: '待补证',
    unknown: '未知',
  };
  return labels[quality] ?? quality;
}

function qualityClass(quality: string): string {
  if (quality === 'high') return 'teal';
  if (quality === 'low') return 'amber';
  return 'gray';
}

function rawStatusLabel(rawAvailable?: boolean, rawStatus?: string): string {
  if (rawAvailable) return '已上传原文，可直接排查';
  if (rawStatus === '无证据投影') return '本条没有证据投影';
  return '未上传原文，可查看摘要和字段';
}

function technicalRefLabel(entry: SignalEvidenceItem): string {
  const factPart = entry.fact_id ? `命中引用 ${shortRef(entry.fact_id)}` : '补证结果';
  return `${factPart} · 引用 ${shortRef(entry.evidence_ref)}`;
}

function shortRef(evidenceRef: string): string {
  if (evidenceRef.length <= 18) return evidenceRef;
  return `${evidenceRef.slice(0, 14)}...${evidenceRef.slice(-6)}`;
}
