"""collector 503 重试逻辑测试：指数退避 + outbox 上限保护。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.collector_client.config import CollectorConfig, SourceConfig
from app.collector_client.runtime import _backoff_seconds, _outbox_soft_limit


def test_backoff_sequence():
    """连续失败时退避时间递增，上限60秒。"""
    assert _backoff_seconds(1) == 5
    assert _backoff_seconds(2) == 10
    assert _backoff_seconds(3) == 20
    assert _backoff_seconds(4) == 40
    assert _backoff_seconds(5) == 60
    assert _backoff_seconds(10) == 60
    assert _backoff_seconds(100) == 60


def test_backoff_first_error_is_5s():
    """第一次失败退避5秒（与原行为一致）。"""
    assert _backoff_seconds(1) == 5


def _make_config(tmp_path: Path) -> CollectorConfig:
    return CollectorConfig(
        server_url="http://127.0.0.1:8765",
        collector_id="collector-test",
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


def _make_state() -> dict:
    return {
        "running": True,
        "cursor": {"last_sequence": 0},
        "outbox": [],
        "runtime_phase": "idle",
        "source_status": "online",
        "reason_code": "idle",
        "last_error": None,
        "effective_policy": {},
    }


def test_outbox_soft_limit_default_fallback():
    """state 无 effective_policy 时回退到默认值 5000。"""
    assert _outbox_soft_limit({}) == 5000
    assert _outbox_soft_limit({"effective_policy": {}}) == 5000


def test_outbox_soft_limit_reads_from_policy():
    """从 state.effective_policy 读取 outbox_soft_limit。"""
    state = {"effective_policy": {"outbox_soft_limit": 8000}}
    assert _outbox_soft_limit(state) == 8000


def test_outbox_soft_limit_clamps_invalid_to_default():
    """越界的 policy 值回退到默认值。"""
    assert _outbox_soft_limit({"effective_policy": {"outbox_soft_limit": 100}}) == 5000
    assert _outbox_soft_limit({"effective_policy": {"outbox_soft_limit": 99999}}) == 5000
    assert _outbox_soft_limit({"effective_policy": {"outbox_soft_limit": "abc"}}) == 5000


def _write_state(tmp_path: Path, state: dict) -> None:
    (tmp_path / "agent-observer.state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def test_run_once_skips_collect_when_outbox_backlog_exceeds_limit(tmp_path):
    """outbox 积压超过 outbox_soft_limit 时跳过采集，只上传。"""
    from app.collector_client.runtime import _run_once

    config = _make_config(tmp_path)
    # 预填充 outbox 到超限（policy 设为 1000，填充 1100 条）
    state = _make_state()
    state["effective_policy"] = {"outbox_soft_limit": 1000}
    state["outbox"] = [
        {
            "source_event_id": f"event-{i}",
            "source_refs": {
                "sequence": i + 1,
                "source_id": "codex-local",
                "agent_type": "codex",
                "source_kind": "codex_local",
            },
        }
        for i in range(1100)
    ]
    _write_state(tmp_path, state)

    # mock 采集返回空（验证不被调用）
    with patch("app.collector_client.runtime.collect_sources") as mock_collect:
        mock_collect.return_value = []
        # mock 上传成功清空 outbox
        with patch("app.collector_client.runtime._upload_pending", return_value=0):
            with patch("app.collector_client.runtime._run_pending_enrichment", return_value=[]):
                with patch("app.collector_client.runtime._register_collector"):
                    with patch("app.collector_client.runtime._refresh_policy_config", return_value=config):
                        _run_once(config, heartbeat_reason="test", register=False)

        # 采集不应被调用
        mock_collect.assert_not_called()
