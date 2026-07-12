from __future__ import annotations

import json
from pathlib import Path

from app.collector_client.cli import run
from app.collector_client.runtime import CommandResult


def test_start_triggers_auto_discovery_and_creates_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    captured: list = []

    def fake_start(config, emit):
        captured.append(config)
        return CommandResult(0, json.dumps({"status": "ok", "mode": "started", "collector_id": config.collector_id}))

    monkeypatch.setattr("app.collector_client.cli._start", fake_start)

    result = run(["start"], cwd=workdir)

    assert result.code == 0
    assert (workdir / "agent-observer.config.json").exists()
    assert len(captured) == 1
    assert captured[0].collector_id


def test_status_without_config_returns_error_and_does_not_create_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    result = run(["status"], cwd=workdir)
    payload = json.loads(result.output)

    assert result.code == 2
    assert payload["status"] == "error"
    assert payload["error"] == "missing_config"
    assert not (workdir / "agent-observer.config.json").exists()


def test_doctor_without_config_and_agent_installed_returns_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    workdir = tmp_path / "work"
    workdir.mkdir()

    result = run(["doctor"], cwd=workdir)
    payload = json.loads(result.output)

    assert result.code == 2
    assert not (workdir / "agent-observer.config.json").exists()
    assert "Claude Code" in json.dumps(payload, ensure_ascii=False)


def test_doctor_without_config_and_no_agent_returns_no_agent_message(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()

    result = run(["doctor"], cwd=workdir)
    payload = json.loads(result.output)

    assert result.code == 2
    assert not (workdir / "agent-observer.config.json").exists()
    assert "未发现已安装的 Agent" in json.dumps(payload, ensure_ascii=False)
