from __future__ import annotations

import sqlite3

from app.conversations.workspace import workspace_from_source_refs, workspace_key, workspace_matches


def workspaces_from_facts(facts: list[sqlite3.Row]) -> list[dict]:
    result: dict[str, dict] = {}
    for fact in facts:
        workspace = workspace_from_source_refs(fact["source_refs_json"])
        key = workspace_key(workspace)
        if key != "unknown":
            result.setdefault(key, workspace)
    return list(result.values())


def workspace_summary(workspaces: list[dict]) -> dict:
    if not workspaces:
        return {"mode": "unknown", "label": "工作区未知", "count": 0}
    if len(workspaces) == 1:
        workspace = workspaces[0]
        return {
            "mode": "single",
            "label": workspace.get("workspace_label") or workspace.get("workspace_path") or "工作区未知",
            "count": 1,
        }
    return {"mode": "multiple", "label": f"涉及 {len(workspaces)} 个工作区", "count": len(workspaces)}


def signal_workspace_matches(signal: dict, query: str) -> bool:
    return any(workspace_matches(workspace, query) for workspace in signal.get("workspace_refs", []))
