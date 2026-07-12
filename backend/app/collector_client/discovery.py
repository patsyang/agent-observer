from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredSource:
    source_kind: str
    agent_type: str
    root: Path
    display_name: str


def _discovery_rules() -> list[dict]:
    """延迟调用 Path.home()，支持测试 monkeypatch。"""
    home = Path.home()
    return [
        {
            "source_kind": "claude_local",
            "agent_type": "claude",
            "display_name": "Claude Code",
            "root": home / ".claude",
            "marker": "projects",
        },
        {
            "source_kind": "codex_local",
            "agent_type": "codex",
            "display_name": "Codex",
            "root": home / ".codex",
            "marker": "sessions",
        },
        {
            "source_kind": "workbuddy_local",
            "agent_type": "workbuddy",
            "display_name": "WorkBuddy",
            "root": home / ".workbuddy",
            "marker": "sessions",
        },
    ]


def discover_sources() -> list[DiscoveredSource]:
    found: list[DiscoveredSource] = []
    for rule in _discovery_rules():
        root: Path = rule["root"]
        if root.is_dir() and (root / rule["marker"]).is_dir():
            found.append(
                DiscoveredSource(
                    source_kind=rule["source_kind"],
                    agent_type=rule["agent_type"],
                    root=root,
                    display_name=rule["display_name"],
                )
            )
    return found
