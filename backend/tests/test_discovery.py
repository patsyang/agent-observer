from __future__ import annotations

from pathlib import Path

from app.collector_client.discovery import DiscoveredSource, discover_sources


def test_discover_claude_when_projects_dir_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)

    found = discover_sources()

    assert len(found) == 1
    source = found[0]
    assert isinstance(source, DiscoveredSource)
    assert source.source_kind == "claude_local"
    assert source.agent_type == "claude"
    assert source.root == tmp_path / ".claude"
    assert source.display_name == "Claude Code"


def test_discover_codex_when_sessions_dir_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)

    found = discover_sources()

    assert len(found) == 1
    source = found[0]
    assert source.source_kind == "codex_local"
    assert source.agent_type == "codex"
    assert source.root == tmp_path / ".codex"
    assert source.display_name == "Codex"


def test_discover_multiple_agents_when_both_dirs_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)

    found = discover_sources()

    assert len(found) == 2
    kinds = {source.source_kind for source in found}
    assert kinds == {"claude_local", "codex_local"}


def test_discover_returns_empty_when_no_agent_dirs_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    found = discover_sources()

    assert found == []


def test_discover_returns_empty_when_claude_dir_without_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude").mkdir(parents=True)

    found = discover_sources()

    assert found == []
