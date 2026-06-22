from __future__ import annotations

import json
import sqlite3


def workspace_from_rows(rows: list[sqlite3.Row]) -> dict:
    for row in rows:
        workspace = workspace_from_source_refs(row["source_refs_json"])
        if workspace.get("workspace_id") or workspace.get("workspace_path"):
            return workspace
    return empty_workspace()


def workspace_from_source_refs(source_refs_json: str | None) -> dict:
    try:
        refs = json.loads(source_refs_json or "{}")
    except json.JSONDecodeError:
        refs = {}
    return {
        "agent_type": str(refs.get("agent_type") or ""),
        "workspace_id": str(refs.get("workspace_id") or ""),
        "workspace_path": str(refs.get("workspace_path") or ""),
        "workspace_label": str(refs.get("workspace_label") or ""),
        "workspace_alias_source": str(refs.get("workspace_alias_source") or ""),
        "workspace_confidence": str(refs.get("workspace_confidence") or "unknown"),
    }


def empty_workspace() -> dict:
    return {
        "agent_type": "",
        "workspace_id": "",
        "workspace_path": "",
        "workspace_label": "",
        "workspace_alias_source": "",
        "workspace_confidence": "unknown",
    }


def workspace_matches(workspace: dict, query: str | None) -> bool:
    value = (query or "").strip().lower()
    if not value:
        return True
    haystack = " ".join(str(workspace.get(key) or "") for key in ("workspace_label", "workspace_path", "workspace_id", "agent_type"))
    return value in haystack.lower()


def workspace_key(workspace: dict) -> str:
    return str(workspace.get("workspace_id") or workspace.get("workspace_path") or "unknown")
