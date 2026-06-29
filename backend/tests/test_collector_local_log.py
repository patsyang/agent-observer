from __future__ import annotations

import json

from app.collector_client.cli import _human_log_line, run


def _write_config(tmp_path, collector_id: str, state_path, interval: int = 30) -> None:
    (tmp_path / "agent-observer.config.json").write_text(
        json.dumps(
            {
                "server_url": "http://127.0.0.1:8765",
                "collector_id": collector_id,
                "state_path": str(state_path),
                "telemetry_mode": "safe_probe",
                "collection_interval_seconds": interval,
                "sources": [
                    {
                        "source_id": "codex-local",
                        "agent_type": "codex",
                        "source_kind": "codex_local",
                        "display_name": "Codex Local",
                        "root": str(tmp_path / ".codex"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _fact() -> dict:
    return {
        "fact_type": "tool",
        "category": "tool_call",
        "source_refs": {
            "sequence": 1,
            "source_id": "codex-local",
            "agent_type": "codex",
            "source_kind": "codex_local",
        },
    }


def _read_log_entries(tmp_path) -> list[dict]:
    return [
        json.loads(line)
        for line in (tmp_path / "logs" / "collector.log").read_text(encoding="utf-8").splitlines()
    ]


def test_run_once_writes_local_collector_log_with_runtime_events(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-local-log", state_path)
    fact = _fact()

    def fake_collect(config, _state, _sequence, emit=None, cycle=None):
        if emit:
            emit(
                {
                    "status": "ok",
                    "mode": "source_started",
                    "cycle": cycle,
                    "source_id": "codex-local",
                    "agent_type": "codex",
                    "display_name": "C:\\Users\\dev\\.codex",
                }
            )
        return [type("Result", (), {"facts": [fact], "config": config.sources[0], "status": "online", "reason_code": "collected"})()]

    monkeypatch.setattr("app.collector_client.runtime._register_collector", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.collector_client.runtime.collect_sources", fake_collect)
    monkeypatch.setattr("app.collector_client.runtime._post_json", lambda *_args, **_kwargs: {})

    result = run(["run-once"], cwd=tmp_path)

    assert result.code == 0
    entries = _read_log_entries(tmp_path)
    modes = [entry["mode"] for entry in entries]
    assert "cycle_started" in modes
    assert "source_started" in modes
    assert "upload_completed" in modes
    assert "cycle" in modes
    assert all(entry["collector_id"] == "collector-local-log" for entry in entries)
    assert all("logged_at" in entry for entry in entries)
    assert any(entry.get("display_name") == "C:\\Users\\dev\\.codex" for entry in entries)


def test_run_once_local_log_keeps_full_error_while_human_stdout_stays_redacted(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-local-error", state_path)
    sensitive_error = "failed opening C:\\Users\\dev\\.codex\\sessions\\a.jsonl"
    fact = _fact()

    def fake_collect(_config, _state, _sequence, emit=None, cycle=None):
        return [type("Result", (), {"facts": [fact], "config": _config.sources[0], "status": "online", "reason_code": "collected"})()]

    def fail_upload(*_args, **_kwargs):
        raise OSError(sensitive_error)

    monkeypatch.setattr("app.collector_client.runtime._register_collector", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.collector_client.runtime.collect_sources", fake_collect)
    monkeypatch.setattr("app.collector_client.runtime._post_json", fail_upload)

    result = run(["run-once"], cwd=tmp_path)
    human_line = _human_log_line({**json.loads(result.output), "mode": "cycle_error", "cycle": 1})
    entries = _read_log_entries(tmp_path)

    assert result.code == 2
    assert any(entry.get("error") == sensitive_error for entry in entries)
    assert any("Traceback" in str(entry.get("traceback")) for entry in entries)
    assert "采集或上传失败" in human_line
    assert "C:\\" not in human_line
    assert ".jsonl" not in human_line
