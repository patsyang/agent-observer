from __future__ import annotations

import json

import pytest

from app.collector_client.config import CollectorConfig, SourceConfig
from app.collector_client.runtime import _upload_pending


def _config(tmp_path) -> CollectorConfig:
    return CollectorConfig(
        server_url="http://127.0.0.1:8765",
        collector_id="collector-timeout",
        state_path=tmp_path / "agent-observer.state.json",
        telemetry_mode="fixture",
        collection_interval_seconds=5,
        heartbeat_interval_seconds=10,
        sources=[
            SourceConfig(
                source_id="codex-local",
                agent_type="codex",
                source_kind="codex_local",
                display_name="Codex",
                root=tmp_path / ".codex",
                enabled=True,
            )
        ],
        history_window_days=7,
        max_events_per_cycle=500,
        upload_batch_size=100,
        evidence_mode="structured_projection",
    )


def _state() -> dict:
    return {
        "running": True,
        "cursor": {"last_sequence": 0},
        "outbox": [
            {
                "source_event_id": "event-timeout",
                "source_refs": {
                    "sequence": 1,
                    "source_id": "codex-local",
                    "agent_type": "codex",
                    "source_kind": "codex_local",
                },
            }
        ],
    }


def test_timeout_with_accepted_batch_removes_outbox(tmp_path, monkeypatch):
    config = _config(tmp_path)
    state = _state()
    emitted: list[dict] = []

    def fake_post(_server_url, path, _payload):
        if path == "/api/telemetry/ingest":
            raise TimeoutError("timed out")
        return {"effective_policy": {"raw_upload_mode": "always_on"}}

    def fake_get(_server_url, path):
        assert path.startswith("/api/telemetry/batches/")
        return {"status": "accepted", "accepted_count": 1, "duplicate_count": 0, "created_at": "now"}

    monkeypatch.setattr("app.collector_client.runtime._post_json", fake_post)
    monkeypatch.setattr("app.collector_client.upload_ack._get_json", fake_get)

    uploaded = _upload_pending(config, state, "run_once_completed", emit=lambda line: emitted.append(json.loads(line)))

    assert uploaded == 1
    assert state["outbox"] == []
    assert [item["mode"] for item in emitted][:2] == ["upload_timeout_check", "upload_timeout_confirmed"]


def test_http_gateway_timeout_with_accepted_batch_removes_outbox(tmp_path, monkeypatch):
    config = _config(tmp_path)
    state = _state()

    def fake_post(_server_url, path, _payload):
        if path == "/api/telemetry/ingest":
            raise ValueError("http_error:504")
        return {"effective_policy": {"raw_upload_mode": "always_on"}}

    monkeypatch.setattr("app.collector_client.runtime._post_json", fake_post)
    monkeypatch.setattr(
        "app.collector_client.upload_ack._get_json",
        lambda *_args: {"status": "accepted", "accepted_count": 1, "duplicate_count": 0, "created_at": "now"},
    )

    uploaded = _upload_pending(config, state, "run_once_completed")

    assert uploaded == 1
    assert state["outbox"] == []


def test_timeout_with_missing_batch_keeps_outbox(tmp_path, monkeypatch):
    config = _config(tmp_path)
    state = _state()

    def fake_post(_server_url, path, _payload):
        if path == "/api/telemetry/ingest":
            raise TimeoutError("timed out")
        return {"effective_policy": {"raw_upload_mode": "always_on"}}

    monkeypatch.setattr("app.collector_client.runtime._post_json", fake_post)
    monkeypatch.setattr("app.collector_client.upload_ack._get_json", lambda *_args: {"status": "missing"})

    with pytest.raises(TimeoutError, match="batch_acceptance_unconfirmed"):
        _upload_pending(config, state, "run_once_completed")

    assert len(state["outbox"]) == 1
