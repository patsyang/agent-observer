"""Tests for usage anomaly detection: usage_spike, low_cache_hit_rate, unknown_usage_dominant."""
from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.behavior_signals.service import rebuild_signals, list_signals
from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.processing.jobs import run_next_job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmpdb():
    path = Path(tempfile.mktemp(suffix=".sqlite"))
    yield path
    import gc
    gc.collect()
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


def _usage_batch(items: list[dict]) -> dict:
    if not items:
        items = [{}]
    batch_id = f"batch-usage-{items[0].get('source_event_id', '0')}"
    return {
        "batch_id": batch_id,
        "protocol_version": "agent-observer-telemetry/v3",
        "agent_version": "0.3.0",
        "collector_id": "collector-codex",
        "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
        "cursor": "cursor-usage",
        "items": items,
    }


def _ingest(conn, items: list[dict]) -> None:
    ingest_telemetry(conn, _usage_batch(items))
    while run_next_job(conn, reason="test")["processed"]:
        pass


def _usage_item(
    event_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    activity_tag: str = "implementation",
    conversation_ref: str = "conv-1",
    session_ref: str = "session-1",
    account_ref: str = "account-local",
    occurred_at: str | None = None,
    cache_observed: bool = True,
) -> dict:
    if occurred_at is None:
        occurred_at = "2026-06-18T10:00:00+00:00"
    return {
        "source_event_id": event_id,
        "fact_type": "usage",
        "category": "usage",
        "quality": "high",
        "severity": "low",
        "summary": f"Usage {event_id}",
        "occurred_at": occurred_at,
        "span": f"session:{session_ref}",
        "raw_hash": f"hash-{event_id}",
        "projection": {"activity_tag": activity_tag},
        "usage": {
            "scope": "session",
            "units": input_tokens + output_tokens,
            "activity_tag": activity_tag,
            "session_id": session_ref,
            "conversation_id": conversation_ref,
            "account_ref": account_ref,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_observed": cache_observed,
            "unit_basis": "non_cached_input_plus_output",
            "observability_level": "full",
        },
        "source_refs": {"conversation_ref": conversation_ref, "session_ref": session_ref},
        "source_specific": {"event_type": "usage_summary"},
    }


# ---------------------------------------------------------------------------
# usage_spike tests
# ---------------------------------------------------------------------------

def test_usage_spike_triggered_when_total_tokens_exceeds_100k(tmpdb):
    """Single usage fact with input+output > 100,000 triggers usage_spike signal."""
    item = _usage_item(
        event_id="spike-001",
        input_tokens=80_000,
        output_tokens=50_000,  # total 130,000
        activity_tag="debugging",
    )
    with connect(tmpdb) as conn:
        _ingest(conn, [item])
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "usage_spike"]
    assert len(signals) == 1
    assert signals[0]["priority_score"] == 70
    assert signals[0]["severity"] == "medium"
    assert "用量突增" in signals[0]["title"]
    assert signals[0]["affected_scope"]["total_tokens"] == 130_000


def test_usage_spike_not_triggered_below_threshold(tmpdb):
    """input+output <= 100,000 should not trigger usage_spike."""
    item = _usage_item(
        event_id="normal-001",
        input_tokens=50_000,
        output_tokens=49_000,  # total 99,000
    )
    with connect(tmpdb) as conn:
        _ingest(conn, [item])
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "usage_spike"]
    assert len(signals) == 0


def test_usage_spike_multiple_facts_grouped(tmpdb):
    """Multiple spike facts in same conversation grouped into one signal."""
    items = [
        _usage_item(event_id="spike-1", input_tokens=60_000, output_tokens=50_000, conversation_ref="conv-a"),
        _usage_item(event_id="spike-2", input_tokens=70_000, output_tokens=40_000, conversation_ref="conv-a"),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "usage_spike"]
    assert len(signals) == 1
    assert signals[0]["affected_scope"]["conversation_count"] == 1
    assert signals[0]["affected_scope"]["fact_count"] == 2


# ---------------------------------------------------------------------------
# low_cache_hit_rate tests
# ---------------------------------------------------------------------------

def test_low_cache_hit_rate_triggered(tmpdb):
    """input > 10,000 and cache_hit_rate < 10% triggers low_cache_hit_rate signal."""
    item = _usage_item(
        event_id="nocache-001",
        input_tokens=50_000,
        output_tokens=1_000,
        cached_input_tokens=1_000,  # hit rate = 1_000/50_000 = 2%
        activity_tag="coding",
    )
    with connect(tmpdb) as conn:
        _ingest(conn, [item])
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "low_cache_hit_rate"]
    assert len(signals) == 1
    assert signals[0]["priority_score"] == 65
    assert signals[0]["severity"] == "medium"
    assert "缓存命中率过低" in signals[0]["title"]
    assert signals[0]["affected_scope"]["cache_hit_rate"] < 0.10


def test_low_cache_hit_rate_not_triggered_when_cache_high(tmpdb):
    """High cache hit rate should not trigger."""
    item = _usage_item(
        event_id="good-cache-001",
        input_tokens=50_000,
        output_tokens=1_000,
        cached_input_tokens=40_000,  # hit rate = 80%
        activity_tag="coding",
    )
    with connect(tmpdb) as conn:
        _ingest(conn, [item])
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "low_cache_hit_rate"]
    assert len(signals) == 0


def test_low_cache_hit_rate_not_triggered_when_input_small(tmpdb):
    """Small input (< 10,000) should not trigger even with low cache rate."""
    item = _usage_item(
        event_id="small-001",
        input_tokens=500,
        output_tokens=100,
        cached_input_tokens=0,
        activity_tag="testing",
    )
    with connect(tmpdb) as conn:
        _ingest(conn, [item])
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "low_cache_hit_rate"]
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# unknown_usage_dominant tests
# ---------------------------------------------------------------------------

def test_unknown_usage_dominant_triggered(tmpdb):
    """Within 1-hour window, unknown activity_tag > 50% triggers signal."""
    now = datetime.now(UTC).replace(microsecond=0)
    items = [
        _usage_item(
            event_id=f"unknown-{i}",
            input_tokens=100,
            output_tokens=50,
            activity_tag="unknown",
            account_ref="account-alpha",
            occurred_at=(now - timedelta(minutes=i * 5)).isoformat(),
        )
        for i in range(6)
    ] + [
        _usage_item(
            event_id="known-001",
            input_tokens=200,
            output_tokens=100,
            activity_tag="implementation",
            account_ref="account-alpha",
            occurred_at=(now - timedelta(minutes=2)).isoformat(),
        ),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "unknown_usage_dominant"]
    assert len(signals) == 1
    assert signals[0]["priority_score"] == 60
    assert "未知用量主导" in signals[0]["title"]
    assert signals[0]["affected_scope"]["unknown_ratio"] > 0.50


def test_unknown_usage_dominant_not_triggered_when_below_threshold(tmpdb):
    """Unknown ratio <= 50% should not trigger."""
    now = datetime.now(UTC).replace(microsecond=0)
    items = [
        _usage_item(
            event_id=f"unknown-{i}",
            input_tokens=100,
            activity_tag="unknown",
            account_ref="account-beta",
            occurred_at=(now - timedelta(minutes=i * 5)).isoformat(),
        )
        for i in range(3)
    ] + [
        _usage_item(
            event_id=f"known-{i}",
            input_tokens=100,
            activity_tag="implementation",
            account_ref="account-beta",
            occurred_at=(now - timedelta(minutes=10 + i * 5)).isoformat(),
        )
        for i in range(3)
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "unknown_usage_dominant"]
    assert len(signals) == 0


def test_unknown_usage_dominant_outside_window_not_triggered(tmpdb):
    """Facts older than 1 hour should not be considered."""
    old_at = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0).isoformat()
    item = _usage_item(
        event_id="old-unknown",
        input_tokens=100,
        activity_tag="unknown",
        account_ref="account-old",
        occurred_at=old_at,
    )
    with connect(tmpdb) as conn:
        _ingest(conn, [item])
        rebuild_signals(conn, reason="test")

    signals = [s for s in list_signals(conn)["signals"] if s["signal_kind"] == "unknown_usage_dominant"]
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

def test_integration_all_three_anomaly_types(tmpdb):
    """End-to-end: ingest facts triggering all three anomaly types simultaneously."""
    now = datetime.now(UTC).replace(microsecond=0)
    items = [
        # usage_spike
        _usage_item(
            event_id="spike-001",
            input_tokens=80_000,
            output_tokens=50_000,
            activity_tag="debugging",
            conversation_ref="conv-spike",
            session_ref="session-spike",
        ),
        # low_cache_hit_rate
        _usage_item(
            event_id="nocache-001",
            input_tokens=50_000,
            output_tokens=1_000,
            cached_input_tokens=500,  # ~1% hit rate
            activity_tag="coding",
            conversation_ref="conv-cache",
            session_ref="session-cache",
        ),
        # unknown_usage_dominant
        _usage_item(
            event_id="unknown-001",
            input_tokens=100,
            activity_tag="unknown",
            account_ref="account-mixed",
            occurred_at=(now - timedelta(minutes=10)).isoformat(),
        ),
        _usage_item(
            event_id="unknown-002",
            input_tokens=100,
            activity_tag="unknown",
            account_ref="account-mixed",
            occurred_at=(now - timedelta(minutes=5)).isoformat(),
        ),
        _usage_item(
            event_id="known-001",
            input_tokens=100,
            activity_tag="implementation",
            account_ref="account-mixed",
            occurred_at=(now - timedelta(minutes=2)).isoformat(),
        ),
    ]
    with connect(tmpdb) as conn:
        _ingest(conn, items)
        rebuild_signals(conn, reason="test")

    all_signals = list_signals(conn)["signals"]
    kinds = {s["signal_kind"] for s in all_signals}
    assert "usage_spike" in kinds
    assert "low_cache_hit_rate" in kinds
    assert "unknown_usage_dominant" in kinds

    spike = next(s for s in all_signals if s["signal_kind"] == "usage_spike")
    assert spike["priority_score"] == 70
    assert spike["affected_scope"]["total_tokens"] == 130_000

    cache = next(s for s in all_signals if s["signal_kind"] == "low_cache_hit_rate")
    assert cache["priority_score"] == 65
    assert cache["affected_scope"]["cache_hit_rate"] < 0.10

    unknown = next(s for s in all_signals if s["signal_kind"] == "unknown_usage_dominant")
    assert unknown["priority_score"] == 60
    assert unknown["affected_scope"]["unknown_count"] == 2
