import type { ToolContext } from '../api/types';
import { formatNumber } from '../utils/numberFormat';

interface Props {
  context?: ToolContext | null;
  compact?: boolean;
}

export function ToolContextBlock({ context, compact = false }: Props) {
  if (!context) return null;
  const command = context.command || context.command_excerpt;
  return (
    <div className={compact ? 'tool-context tool-context--compact' : 'tool-context'}>
      {context.tool_name && <p>工具：{context.tool_name}</p>}
      {command && <p>命令：{command}</p>}
      <p>{context.is_timeout ? '状态：超时' : `退出码：${context.exit_code ?? '未知'}`}</p>
      {context.wall_time_seconds !== null && context.wall_time_seconds !== undefined && (
        <p>运行时长：{formatNumber(Math.round(context.wall_time_seconds))} 秒</p>
      )}
      {context.timeout_after_ms !== null && context.timeout_after_ms !== undefined && (
        <p>超时阈值：{formatNumber(context.timeout_after_ms)} ms</p>
      )}
      {context.error_excerpt && <p>错误摘要：{context.error_excerpt}</p>}
    </div>
  );
}

export function primaryToolContext(items: Array<{ tool_context?: ToolContext | null }>): ToolContext | null {
  return items.find((item) => item.tool_context)?.tool_context ?? null;
}
