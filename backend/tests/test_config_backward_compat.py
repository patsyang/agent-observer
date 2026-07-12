from __future__ import annotations

import json

from app.collector_client.config import _DEFAULTS, load_config


def test_full_config_file_loads_all_fields(tmp_path):
    """完整 config 文件的所有字段应被正确加载，值与 _DEFAULTS 一致。"""
    config_path = tmp_path / "agent-observer.config.json"
    config_path.write_text(
        json.dumps(
            {
                "server_url": "http://localhost:8000",
                "collector_id": "test-collector",
                "state_path": "agent-observer.state.json",
                "telemetry_mode": _DEFAULTS["telemetry_mode"],
                "collection_interval_seconds": _DEFAULTS["collection_interval_seconds"],
                "heartbeat_interval_seconds": _DEFAULTS["heartbeat_interval_seconds"],
                "sources": [
                    {
                        "source_id": "codex-local",
                        "agent_type": "codex",
                        "source_kind": "codex_local",
                        "display_name": "Codex Local",
                        "root": str(tmp_path / ".codex"),
                    }
                ],
                "history_window_days": _DEFAULTS["history_window_days"],
                "max_events_per_cycle": _DEFAULTS["max_events_per_cycle"],
                "upload_batch_size": _DEFAULTS["upload_batch_size"],
                "evidence_mode": _DEFAULTS["evidence_mode"],
            }
        ),
        encoding="utf-8",
    )

    config, error = load_config(tmp_path)

    assert error is None
    assert config is not None
    assert config.telemetry_mode == _DEFAULTS["telemetry_mode"]
    assert config.collection_interval_seconds == _DEFAULTS["collection_interval_seconds"]
    assert config.heartbeat_interval_seconds == _DEFAULTS["heartbeat_interval_seconds"]
    assert config.history_window_days == _DEFAULTS["history_window_days"]
    assert config.max_events_per_cycle == _DEFAULTS["max_events_per_cycle"]
    assert config.upload_batch_size == _DEFAULTS["upload_batch_size"]
    assert config.evidence_mode == _DEFAULTS["evidence_mode"]


def test_minimal_config_file_uses_defaults(tmp_path):
    """缺少可选字段的 config 应回退到 _DEFAULTS。"""
    config_path = tmp_path / "agent-observer.config.json"
    config_path.write_text(
        json.dumps(
            {
                "server_url": "http://localhost:8000",
                "collector_id": "test-collector",
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

    config, error = load_config(tmp_path)

    assert error is None
    assert config is not None
    assert config.telemetry_mode == _DEFAULTS["telemetry_mode"]
    assert config.collection_interval_seconds == _DEFAULTS["collection_interval_seconds"]
    assert config.heartbeat_interval_seconds == _DEFAULTS["heartbeat_interval_seconds"]
    assert config.history_window_days == _DEFAULTS["history_window_days"]
    assert config.max_events_per_cycle == _DEFAULTS["max_events_per_cycle"]
    assert config.upload_batch_size == _DEFAULTS["upload_batch_size"]
    assert config.evidence_mode == _DEFAULTS["evidence_mode"]
