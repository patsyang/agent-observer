from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.collector_client.config import load_config
from app.collector_client.cli import _human_log_line, _post_heartbeat, _state_payload, run


def _write_config(tmp_path, collector_id: str, state_path, interval: int = 30) -> None:
    (tmp_path / "agent-observer.config.json").write_text(
        json.dumps(
            {
                "server_url": "http://127.0.0.1:8765",
                "collector_id": collector_id,
                "state_path": str(state_path),
                "telemetry_mode": "safe_probe",
                "collection_interval_seconds": interval,
            }
        ),
        encoding="utf-8",
    )


def _write_state(state_path, **overrides) -> None:
    state = {
        "running": True,
        "cursor": {"last_sequence": 2, "last_source_key": ""},
        "outbox": [],
        "last_upload_at": None,
        "last_error": None,
        "process_heartbeat_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    }
    state.update(overrides)
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_state_payload_summarizes_cursor_without_recent_source_keys():
    payload = _state_payload(
        {
            "running": True,
            "cursor": {
                "last_sequence": 7,
                "last_source_key": "C:/Users/dev/.codex/sessions/session.jsonl:00001000",
                "recent_source_keys": ["one", "two"],
            },
            "outbox": [],
            "last_upload_at": "2026-06-20T01:00:00+00:00",
            "last_error": None,
            "raw_upload_enabled": True,
            "process_heartbeat_at": "2026-06-20T01:00:00+00:00",
        },
        compact=True,
    )

    expected = {
        "last_sequence": 7,
        "last_source_key": "session.jsonl:00001000",
        "recent_source_key_count": 2,
        "source_file_count": 0,
    }
    assert payload["cursor_summary"] == expected
    assert "cursor" not in payload


def test_human_cycle_log_is_concise_and_business_readable():
    line = _human_log_line(
        {
            "mode": "cycle",
            "cycle": 12,
            "uploaded": 46,
            "diagnostics": 1,
            "outbox_backlog": 0,
            "last_cycle_duration_ms": 3100,
            "facts_summary": {
                "generated": 46,
                "types": {"error": 2, "risk": 8, "usage": 3, "tool": 33},
            },
            "next_cycle_at": "2026-06-20T01:12:37+00:00",
            "cursor": {
                "last_sequence": 12,
                "recent_source_keys": ["C:/Users/dev/.codex/sessions/a.jsonl:00000001"],
            },
        }
    )

    assert "第 12 轮完成" in line
    assert "生成 46 条事实" in line
    assert "上传 46 条" in line
    assert "错误 2" in line
    assert "风险 8" in line
    assert "补证 1" in line
    assert "source_keys" not in line
    assert ".jsonl" not in line


def test_human_cycle_error_log_does_not_look_successful():
    line = _human_log_line(
        {
            "mode": "cycle_error",
            "cycle": 3,
            "error": "database is locked",
            "outbox_backlog": 90,
            "last_cycle_duration_ms": 60100,
        }
    )

    assert "第 3 轮失败" in line
    assert "database is locked" in line
    assert "outbox 90" in line
    assert "完成" not in line
    assert "生成 0 条事实" not in line


def test_human_wait_log_uses_rounded_seconds_without_four_second_tick():
    first = _human_log_line({"mode": "waiting", "seconds_until_next_cycle": 14})
    second = _human_log_line({"mode": "waiting", "seconds_until_next_cycle": 4})

    assert "14 秒" not in first
    assert "4 秒" not in second
    assert "15 秒" in first
    assert "5 秒" in second


def test_status_reports_stale_liveness_for_old_running_state(tmp_path):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-stale", state_path)
    _write_state(state_path)

    result = run(["status"], cwd=tmp_path)
    payload = json.loads(result.output)

    assert result.code == 0
    assert payload["running"] is False
    assert payload["liveness"] == "stale_state"
    assert "可能异常退出" in payload["message"]


def test_status_reports_busy_when_stale_heartbeat_pid_is_alive(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-busy", state_path)
    _write_state(state_path, process_id=12345)
    monkeypatch.setattr("app.collector_client.status._process_exists", lambda value: value == 12345)

    result = run(["status"], cwd=tmp_path)
    payload = json.loads(result.output)

    assert result.code == 0
    assert payload["running"] is True
    assert payload["liveness"] == "busy"
    assert "采集、上传或补证" in payload["message"]


def test_start_is_idempotent_when_existing_process_is_alive(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-running", state_path, interval=15)
    _write_state(state_path, process_id=12345, process_heartbeat_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr("app.collector_client.status._process_exists", lambda value: value == 12345)
    monkeypatch.setattr("app.collector_client.transport._post_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network not expected")))

    result = run(["start"], cwd=tmp_path)
    payload = json.loads(result.output)

    assert result.code == 0
    assert payload["mode"] == "already_running"
    assert payload["running"] is True


def test_background_heartbeat_post_does_not_rewrite_state_file(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-heartbeat", state_path)
    original_state = {
        "running": True,
        "cursor": {"last_sequence": 3, "sources": {"file": {"line_no": 99}}},
        "outbox": [{"source_event_id": "pending"}],
        "last_upload_at": None,
        "last_error": None,
        "process_heartbeat_at": datetime.now(timezone.utc).isoformat(),
    }
    state_path.write_text(json.dumps(original_state), encoding="utf-8")
    config, error = load_config(tmp_path)
    assert error is None and config is not None
    monkeypatch.setattr("app.collector_client.runtime._post_json", lambda *_args, **_kwargs: {"effective_policy": {"upload_raw": True}})

    _post_heartbeat(config, dict(original_state), "collecting", "collecting")

    assert json.loads(state_path.read_text(encoding="utf-8")) == original_state
