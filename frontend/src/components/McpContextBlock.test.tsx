import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { McpContextBlock } from './McpContextBlock';

describe('McpContextBlock', () => {
  it('renders MCP server and tool info when mcp_server is provided', () => {
    render(
      <McpContextBlock mcpServer="filesystem" mcpTool="read_file" mcpDurationMs={42} mcpIsError={false} />
    );

    expect(screen.getByTestId('mcp-context-block')).toBeInTheDocument();
    expect(screen.getByText('MCP：filesystem / read_file')).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();
  });

  it('shows error marker when mcp_is_error is true', () => {
    render(
      <McpContextBlock mcpServer="github" mcpTool="create_issue" mcpDurationMs={120} mcpIsError={true} />
    );

    expect(screen.getByTestId('mcp-context-block')).toHaveTextContent('MCP：github / create_issue');
    expect(screen.getByTestId('mcp-context-block')).toHaveTextContent('错误：是');
  });

  it('shows no-error marker when mcp_is_error is false', () => {
    render(
      <McpContextBlock mcpServer="github" mcpTool="list_repos" mcpIsError={false} />
    );

    expect(screen.getByTestId('mcp-context-block')).toHaveTextContent('错误：否');
  });

  it('omits duration when not provided', () => {
    render(<McpContextBlock mcpServer="fs" mcpTool="read" />);

    expect(screen.getByTestId('mcp-context-block')).toBeInTheDocument();
    expect(screen.getByTestId('mcp-context-block')).toHaveTextContent('MCP：fs / read');
    expect(screen.getByTestId('mcp-context-block')).not.toHaveTextContent('ms');
  });
});
