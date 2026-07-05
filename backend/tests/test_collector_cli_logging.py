from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.collector_client.config import load_config
from app.collector_client.cli import _human_log_line, _post_heartbeat, run
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


# ---------------------------------------------------------------------------
# 日志脱敏：collector stdout 不得泄露路径细节（项目硬约束）
# ---------------------------------------------------------------------------

def test_human_source_labels_do_not_echo_path_like_display_names():
    """display_name 含路径时，日志不得输出路径片段。"""
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


def test_human_cycle_error_suppresses_path_details():
    """错误日志中的路径细节应被替换为通用提示，不泄露 .jsonl 等扩展名。"""
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


# ---------------------------------------------------------------------------
# 进程管理：status/start 的 liveness 判定与幂等性
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 策略管理：policy 下发与本地 fallback
# ---------------------------------------------------------------------------

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
