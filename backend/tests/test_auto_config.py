from __future__ import annotations

import json
from pathlib import Path

from app.collector_client.config import auto_config, load_config


def test_auto_config_generates_file_when_agent_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("AGENT_OBSERVER_PORT", raising=False)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    config, error = auto_config(workdir)

    assert error is None
    assert config is not None
    assert config.collector_id
    assert config.server_url == "http://localhost:8765"
    assert len(config.sources) == 1
    assert config.sources[0].source_kind == "claude_local"
    assert (workdir / "agent-observer.config.json").exists()


def test_auto_config_reads_env_port(tmp_path, monkeypatch):
    """auto_config 读取 AGENT_OBSERVER_PORT 环境变量"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_OBSERVER_PORT", "9000")
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    config, error = auto_config(workdir)

    assert error is None
    assert config is not None
    assert config.server_url == "http://localhost:9000"


def test_auto_config_explicit_url_overrides_env(tmp_path, monkeypatch):
    """显式 server_url 优先于环境变量"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_OBSERVER_PORT", "9000")
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    config, error = auto_config(workdir, server_url="http://remote:8000")

    assert error is None
    assert config is not None
    assert config.server_url == "http://remote:8000"


def test_auto_config_returns_no_agent_found_when_nothing_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()

    config, error = auto_config(workdir)

    assert config is None
    assert error == "no_agent_found"
    assert not (workdir / "agent-observer.config.json").exists()


def test_load_config_takes_priority_over_auto_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()
    existing_config = {
        "server_url": "http://existing:9000",
        "collector_id": "existing-id",
        "sources": [
            {
                "source_id": "existing-src",
                "agent_type": "codex",
                "source_kind": "codex_local",
                "display_name": "Existing",
                "root": str(tmp_path / ".codex"),
            }
        ],
    }
    (workdir / "agent-observer.config.json").write_text(json.dumps(existing_config), encoding="utf-8")

    config, error = load_config(workdir)

    assert error is None
    assert config is not None
    assert config.collector_id == "existing-id"
    assert config.server_url == "http://existing:9000"


def test_auto_config_round_trip_with_load_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    config, error = auto_config(workdir)
    assert error is None and config is not None

    reloaded, reload_error = load_config(workdir)
    assert reload_error is None
    assert reloaded is not None
    assert reloaded.collector_id == config.collector_id
    assert reloaded.server_url == config.server_url
    assert len(reloaded.sources) == len(config.sources)
    assert {s.source_kind for s in reloaded.sources} == {"claude_local", "codex_local"}
