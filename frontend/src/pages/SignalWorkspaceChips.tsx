import type { SignalWorkspaceRef } from '../api/types';

interface Props {
  workspaces: SignalWorkspaceRef[];
}

export function SignalWorkspaceChips({ workspaces }: Props) {
  return (
    <section aria-label="影响工作区">
      <div className="section-title-row">
        <h3>影响工作区</h3>
        <span>{workspaces.length} 个工作区</span>
      </div>
      {workspaces.length === 0 ? (
        <p>暂无可识别工作区。</p>
      ) : (
        <div className="workspace-chip-row workspace-chip-row--scrollable">
          {workspaces.map((workspace) => (
            <span className="workspace-chip" key={workspace.workspace_id || workspace.workspace_path} title={workspace.workspace_path}>
              <strong>{workspace.workspace_label || '工作区未知'}</strong>
              <small>{workspace.workspace_path || '无路径'}</small>
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
