import type { StoryEvidenceEntry } from '../api/types';
import { formatNumber } from '../utils/numberFormat';
import { factTypeLabel, formatDateTime } from '../pages/dashboardLabels';

interface Props {
  entries: StoryEvidenceEntry[];
  onOpenFact?: (factId: string) => void;
}

const MAX_VISIBLE_EVIDENCE = 20;

export function EvidenceChainTable({ entries, onOpenFact }: Props) {
  if (entries.length === 0) {
    return <p>暂无证据链。请确认采集器已上报结构化事实。</p>;
  }
  const visibleEntries = entries.slice(0, MAX_VISIBLE_EVIDENCE);

  return (
    <div className="evidence-table-wrap">
      {entries.length > visibleEntries.length && (
        <p className="result-note">
          该故事关联 {formatNumber(entries.length)} 条证据，当前展示最关键的前 {formatNumber(visibleEntries.length)} 条；完整排查请进入事实查询按时间和类型过滤。
        </p>
      )}
      <table className="evidence-table responsive-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>真实证据</th>
            <th>类型 / 来源</th>
            <th>可信度 / 原文</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {visibleEntries.map((entry) => (
            <tr key={entry.evidence_ref}>
              <td data-label="时间">{formatDateTime(entry.occurred_at)}</td>
              <td data-label="真实证据">
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
                  <button className="compact-button" type="button" onClick={() => onOpenFact(entry.fact_id as string)}>
                    查看事实
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

function evidenceTypeLabel(entry: StoryEvidenceEntry): string {
  const normalized = entry.category.toLowerCase();
  if (normalized === 'codex_error') return 'Codex 错误';
  if (normalized === 'high_risk_operation') return '高风险操作';
  if (normalized === 'sensitive_object_touch') return '敏感对象触达';
  if (normalized === 'codex_prompt') return '用户 Prompt';
  if (normalized === 'codex_message') return 'Codex 消息';
  if (normalized === 'codex_reasoning') return '推理片段';
  if (normalized === 'usage' || normalized === 'usage_signal') return '用量信号';
  if (normalized === 'diagnostic_result') return '补证结果';
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

function sourceTypeText(entry: StoryEvidenceEntry): string {
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
    diagnostic_result: '补证结果',
    unknown: '未知事件',
  };
  return labels[value || 'unknown'] ?? value ?? '未知事件';
}

function sourceLabelFromRef(evidenceRef: string): string {
  if (evidenceRef.startsWith('diagnostic-result-')) return '白名单补证';
  if (evidenceRef.startsWith('proj-')) return '本机采集器';
  return '结构化事实库';
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

function technicalRefLabel(entry: StoryEvidenceEntry): string {
  const factPart = entry.fact_id ? `事实 ${shortRef(entry.fact_id)}` : '补证结果';
  return `${factPart} · 引用 ${shortRef(entry.evidence_ref)}`;
}

function shortRef(evidenceRef: string): string {
  if (evidenceRef.length <= 18) return evidenceRef;
  return `${evidenceRef.slice(0, 14)}...${evidenceRef.slice(-6)}`;
}
