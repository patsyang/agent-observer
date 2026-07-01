from __future__ import annotations

import re
import sqlite3

from app.conversations.workspace import workspace_from_source_refs, workspace_key, workspace_matches

# ---------------------------------------------------------------------------
# Sensitive path patterns — Linux / Windows / generic credential paths
# ---------------------------------------------------------------------------

_SENSITIVE_PATH_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Linux
    (re.compile(r"/etc/(?:shadow|passwd|sudoers)$"), "linux_system_auth"),
    (re.compile(r"/root/\.ssh/authorized_keys$"), "linux_ssh_trust"),
    # Windows
    (re.compile(r"(?i)(?:Windows|WINDOWS)[\\/]System32[\\/]config[\\/](?:SAM|SECURITY|SYSTEM)(?![a-zA-Z0-9._-])"), "windows_credentials_store"),
    # macOS
    (re.compile(r"Library/(?:Keychains|Security)/"), "macos_keychain"),
    # Generic credential files
    (re.compile(r"(?:^|[\\/\s])\.(?:env|environment)(?:\.local)?(?:\.[a-z]+)?(?![a-zA-Z0-9._-])"), "env_file"),
    (re.compile(r"(?:^|[\\/])(?:\.?credentials|\.?netrc|\.?htpasswd|\.?npmrc|\.?pypirc)(?:\.[a-z]+)?$"), "credential_file"),
    (re.compile(r"(?:^|/)\.ssh/[a-z]*"), "ssh_directory"),
]

SENSITIVE_PATH_PATTERNS: list[tuple[re.Pattern, str]] = _SENSITIVE_PATH_PATTERNS


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
