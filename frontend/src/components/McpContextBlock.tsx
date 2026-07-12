import { formatNumber } from '../utils/numberFormat';

interface Props {
  mcpServer: string;
  mcpTool: string;
  mcpDurationMs?: number | null;
  mcpIsError?: boolean | null;
}

export function McpContextBlock({ mcpServer, mcpTool, mcpDurationMs, mcpIsError }: Props) {
  return (
    <div className="mcp-context" data-testid="mcp-context-block">
      <p>MCP：{mcpServer} / {mcpTool}</p>
      {mcpDurationMs !== null && mcpDurationMs !== undefined && (
        <p>耗时：{formatNumber(mcpDurationMs)} ms</p>
      )}
      <p>错误：{mcpIsError ? '是' : '否'}</p>
    </div>
  );
}
