from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.collector_client.config import load_config
from app.collector_client.cli import _human_log_line, _post_heartbeat, _state_payload, run
from app.collector_client.runtime import CommandResult, _config_with_policy


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


def _write_state(state_path, **overrides) -> None:
    state = {
        "running": True,
        "cursor": {"last_sequence": 2, "sources": {}},
        "outbox": [],
        "last_upload_at": None,
        "last_error": None,
        "process_heartbeat_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
    }
    state.update(overrides)
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_state_payload_summarizes_v2_cursor():
    payload = _state_payload(
        {
            "running": True,
            "cursor": {
                "last_sequence": 7,
                "sources": {"C:/Users/dev/.codex/sessions/session.jsonl": {"line_no": 1000}},
                "live_tail_source_keys": ["one", "two"],
            },
            "outbox": [],
            "last_upload_at": "2026-06-20T01:00:00+00:00",
            "last_error": None,
            "process_heartbeat_at": "2026-06-20T01:00:00+00:00",
        },
        compact=True,
    )

    expected = {
        "last_sequence": 7,
        "source_file_count": 1,
        "live_tail_source_key_count": 2,
    }
    assert payload["cursor_summary"] == expected
    assert "cursor" not in payload
    assert "raw_upload_enabled" not in payload


def test_human_cycle_log_is_concise_and_business_readable():
    line = _human_log_line(
        {
            "mode": "cycle",
            "cycle": 12,
            "uploaded": 46,
            "enrichments": 1,
            "outbox_backlog": 0,
            "last_cycle_duration_ms": 3100,
            "facts_summary": {
                "generated": 46,
                "types": {"error": 2, "risk": 8, "usage": 3, "tool": 33},
            },
            "sources_summary": [
                {
                    "agent_type": "codex",
                    "display_name": "Codex Local",
                    "generated": 38,
                    "types": {"risk": 8, "tool": 30},
                    "status": "online",
                    "reason_code": "collected",
                },
                {
                    "agent_type": "workbuddy",
                    "display_name": "WorkBuddy Local",
                    "generated": 8,
                    "types": {"tool": 3, "usage": 3, "error": 2},
                    "status": "online",
                    "reason_code": "collected",
                },
            ],
            "next_cycle_at": "2026-06-20T01:12:37+00:00",
            "cursor": {
                "last_sequence": 12,
                "live_tail_source_keys": ["C:/Users/dev/.codex/sessions/a.jsonl:00000001"],
            },
        }
    )

    assert "第 12 轮完成" in line
    assert "生成 46 条事实" in line
    assert "上传 46 条" in line
    assert "错误 2" in line
    assert "风险 8" in line
    assert "补证 1" in line
    assert "Codex 38 条" in line
    assert "WorkBuddy 8 条" in line
    assert "source_keys" not in line
    assert ".jsonl" not in line


def test_human_start_and_wait_logs_identify_configured_agents():
    payload = {
        "sources_summary": [
            {"agent_type": "codex", "display_name": "Codex Local"},
            {"agent_type": "workbuddy", "display_name": "WorkBuddy Local"},
        ]
    }

    start = _human_log_line({"mode": "started", "collector_id": "windows-collector", **payload})
    waiting = _human_log_line({"mode": "waiting", "seconds_until_next_cycle": 14, **payload})

    assert "采集 Codex、WorkBuddy" in start
    assert "等待下一轮采集：15 秒" in waiting


def test_human_source_and_upload_logs_identify_agent_without_paths():
    started = _human_log_line({"mode": "source_started", "agent_type": "codex", "display_name": "Codex Local"})
    completed = _human_log_line(
        {
            "mode": "source_completed",
            "agent_type": "workbuddy",
            "display_name": "WorkBuddy Local",
            "source_status": "online",
            "reason_code": "collected",
            "generated": 317,
            "duration_ms": 6900,
        }
    )
    failed = _human_log_line(
        {
            "mode": "source_completed",
            "agent_type": "workbuddy",
            "display_name": "WorkBuddy Local",
            "source_status": "degraded",
            "reason_code": "source_error",
            "duration_ms": 1200,
        }
    )
    uploaded = _human_log_line({"mode": "upload_completed", "uploaded": 817, "batches": 9, "outbox_backlog": 0, "duration_ms": 2100})

    assert "Codex 开始采集" in started
    assert "WorkBuddy 完成：生成 317 条，耗时 6.9s" in completed
    assert "WorkBuddy 采集失败：source_error，下轮继续" in failed
    assert "上传完成：817 条，9 批，outbox 0，耗时 2.1s" in uploaded
    combined = "\n".join([started, completed, failed, uploaded])
    assert "C:\\" not in combined
    assert ".codex" not in combined
    assert ".workbuddy" not in combined


def test_human_source_labels_do_not_echo_path_like_display_names():
    line = _human_log_line(
        {
            "mode": "source_started",
            "agent_type": "codex",
            "display_name": "C:\\Users\\dev\\.codex",
        }
    )

    assert "Codex 开始采集" in line
    assert "C:\\" not in line
    assert ".codex" not in line


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


def test_human_cycle_error_suppresses_path_details():
    line = _human_log_line(
        {
            "mode": "cycle_error",
            "cycle": 3,
            "error": "failed opening C:\\Users\\dev\\.codex\\sessions\\a.jsonl",
            "outbox_backlog": 90,
            "last_cycle_duration_ms": 60100,
        }
    )

    assert "采集或上传失败" in line
    assert "C:\\" not in line
    assert ".jsonl" not in line


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


def test_start_ignores_fresh_heartbeat_when_process_is_missing(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-dead", state_path, interval=15)
    _write_state(state_path, process_id=12345, process_heartbeat_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setattr("app.collector_client.status._process_exists", lambda _value: False)
    monkeypatch.setattr("app.collector_client.runtime._register_collector", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.collector_client.runtime._run_once",
        lambda *_args, **_kwargs: CommandResult(
            0,
            json.dumps({"status": "ok", "facts_summary": {}, "cursor": {"last_sequence": 2, "sources": {}}}),
        ),
    )
    def stop_after_first_wait(config, emit=None):
        state = json.loads(config.state_path.read_text(encoding="utf-8"))
        state["running"] = False
        config.state_path.write_text(json.dumps(state), encoding="utf-8")
        return False

    monkeypatch.setattr("app.collector_client.runtime._sleep_while_running", stop_after_first_wait)

    result = run(["start"], cwd=tmp_path)
    payload = json.loads(result.output)

    assert result.code == 0
    assert payload["mode"] == "stopped"
    assert payload["running"] is False


def test_start_waits_after_zero_fact_cycle_instead_of_auto_stopping(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-empty", state_path, interval=15)
    monkeypatch.setattr("app.collector_client.runtime._register_collector", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "app.collector_client.runtime._run_once",
        lambda *_args, **_kwargs: CommandResult(
            0,
            json.dumps({"status": "ok", "facts_summary": {"generated": 0}, "uploaded": 0, "cursor": {"last_sequence": 1, "sources": {}}}),
        ),
    )
    observed_running = []

    def stop_during_wait(config, emit=None):
        state = json.loads(config.state_path.read_text(encoding="utf-8"))
        observed_running.append(state["running"])
        state["running"] = False
        config.state_path.write_text(json.dumps(state), encoding="utf-8")
        return False

    monkeypatch.setattr("app.collector_client.runtime._sleep_while_running", stop_during_wait)

    result = run(["start"], cwd=tmp_path)
    payload = json.loads(result.output)

    assert result.code == 0
    assert observed_running == [True]
    assert payload["mode"] == "stopped"


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
    monkeypatch.setattr("app.collector_client.runtime._post_json", lambda *_args, **_kwargs: {"effective_policy": {"raw_upload_mode": "always_on"}})

    _post_heartbeat(config, dict(original_state), "collecting", "collecting")

    assert json.loads(state_path.read_text(encoding="utf-8")) == original_state


def test_cached_effective_policy_overrides_local_performance_config(tmp_path):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-policy", state_path, interval=30)
    config, error = load_config(tmp_path)
    assert error is None and config is not None

    effective = _config_with_policy(
        config,
        {
            "effective_policy": {
                "collection_interval_seconds": 5,
                "max_events_per_cycle": 900,
                "upload_batch_size": 120,
            }
        },
    )

    assert effective.collection_interval_seconds == 5
    assert effective.max_events_per_cycle == 900
    assert effective.upload_batch_size == 120
    assert effective.sources == config.sources


def test_run_once_refreshes_policy_before_collecting(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-refresh", state_path, interval=30)
    (tmp_path / ".codex" / "sessions").mkdir(parents=True)
    observed_limits = []

    def fake_collect(config, state, sequence, emit=None, cycle=None):
        observed_limits.append(config.max_events_per_cycle)
        return []

    monkeypatch.setattr(
        "app.collector_client.runtime._post_json",
        lambda *_args, **_kwargs: {
            "effective_policy": {
                "collection_interval_seconds": 5,
                "max_events_per_cycle": 321,
                "upload_batch_size": 120,
            }
        },
    )
    monkeypatch.setattr("app.collector_client.runtime.collect_sources", fake_collect)
    monkeypatch.setattr("app.collector_client.runtime._upload_pending", lambda *_args, **_kwargs: 0)

    result = run(["run-once"], cwd=tmp_path)

    assert result.code == 0
    assert observed_limits == [321]


def test_run_once_register_failure_keeps_local_collection(tmp_path, monkeypatch):
    state_path = tmp_path / "agent-observer.state.json"
    _write_config(tmp_path, "collector-offline-run", state_path, interval=30)
    fact = {"fact_type": "tool", "category": "tool_call", "source_refs": {"sequence": 1}}

    def fake_register(*_args, **_kwargs):
        raise OSError("server offline")

    def fake_collect(_config, _state, _sequence, emit=None, cycle=None):
        return [type("Result", (), {"facts": [fact]})()]

    monkeypatch.setattr("app.collector_client.runtime._register_collector", fake_register)
    monkeypatch.setattr("app.collector_client.runtime.collect_sources", fake_collect)
    monkeypatch.setattr("app.collector_client.runtime._upload_pending", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("upload offline")))

    result = run(["run-once"], cwd=tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result.code == 2
    assert state["outbox"] == [fact]
    assert "server offline" not in state["last_error"]

