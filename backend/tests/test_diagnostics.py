from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.collectors.service import heartbeat, register_collector
from app.db.connection import connect
from app.diagnostics.service import (
    cancel_diagnostic,
    expire_diagnostics,
    get_diagnostic_availability,
    get_next_collector_diagnostic,
    record_diagnostic_result,
    record_collector_diagnostic_result,
    request_diagnostic,
)
from app.ingest.service import ingest_telemetry
from app.stories.service import get_story_detail, rebuild_stories


def _batch(batch_id: str = "batch-diagnostic-001") -> dict:
    return {
        "batch_id": batch_id,
        "collector_id": "collector-diagnostic",
        "source": "codex",
        "cursor": f"cursor-{batch_id}",
        "items": [
            {
                "source_event_id": f"{batch_id}-error",
                "fact_type": "error",
                "category": "codex_error",
                "quality": "high",
                "severity": "high",
                "summary": "Diagnostic fixture command failed",
                "occurred_at": "2026-06-18T12:00:00+00:00",
                "span": "conversation:diagnostic",
                "raw_hash": f"hash-{batch_id}-error",
                "projection": {"signature_key": "sig-diagnostic-fixture"},
                "error_signature": {"signature_key": "sig-diagnostic-fixture", "category": "codex_error"},
                "source_refs": {"conversation_ref": "conversation-diagnostic"},
            }
        ],
    }


def _story(conn) -> str:
    register_collector(
        conn,
        {
            "collector_id": "collector-diagnostic",
            "display_name": "Diagnostic collector",
            "hostname": "diagnostic-host",
            "windows_username": "diagnostic-user",
        },
    )
    heartbeat(conn, "collector-diagnostic", {"source_status": "online", "reason_code": "ok"})
    ingest_telemetry(conn, _batch())
    return rebuild_stories(conn, reason="diagnostic-test")["stories"][0]["story_id"]


def test_diagnostic_success_updates_evidence_chain_and_audit(tmp_path):
    with connect(tmp_path / "diagnostics.sqlite") as conn:
        story_id = _story(conn)

        availability = get_diagnostic_availability(conn, story_id)
        assert availability["capabilities"][0]["state"] == "available"

        job = request_diagnostic(conn, story_id, "codex_error_context")
        assert job["status"] == "pending"
        assert job["command"]["command_id"] == "collect_codex_error_context"
        assert "shell" not in job["command"]

        result = record_diagnostic_result(conn, job["job_id"], "succeeded", "Sanitized stack category matched")
        detail = get_story_detail(conn, story_id)
        rebuilt_detail = get_story_detail(conn, rebuild_stories(conn, reason="after-diagnostic")["stories"][0]["story_id"])
        audits = conn.execute("select action from audit_logs where object_id = ? order by rowid", (story_id,)).fetchall()

    assert result["status"] == "succeeded"
    assert detail["diagnostic_status_summary"]["status"] == "succeeded"
    assert any(entry["category"] == "diagnostic_result" for entry in detail["current_snapshot"]["evidence_chain"])
    assert rebuilt_detail["diagnostic_status_summary"]["status"] == "succeeded"
    assert any(entry["category"] == "diagnostic_result" for entry in rebuilt_detail["current_snapshot"]["evidence_chain"])
    assert detail["handling_state"] == "unread"
    assert [row["action"] for row in audits] == ["diagnostic_requested", "diagnostic_result_recorded"]


def test_collector_pulls_whitelisted_diagnostic_and_returns_result(tmp_path):
    with connect(tmp_path / "diagnostics.sqlite") as conn:
        story_id = _story(conn)
        job = request_diagnostic(conn, story_id, "codex_error_context")

        next_job = get_next_collector_diagnostic(conn, "collector-diagnostic")
        assert next_job["job_id"] == job["job_id"]
        assert next_job["status"] == "running"
        assert next_job["command"]["command_id"] == "collect_codex_error_context"
        assert "shell" not in next_job["command"]

        result = record_collector_diagnostic_result(
            conn,
            "collector-diagnostic",
            job["job_id"],
            {"status": "succeeded", "summary": "错误上下文已匹配", "projection": {"matched_category": "codex_error"}},
        )
        detail = get_story_detail(conn, story_id)

    assert result["status"] == "succeeded"
    assert detail["diagnostic_status_summary"]["status"] == "succeeded"
    assert any(entry["category"] == "diagnostic_result" for entry in detail["current_snapshot"]["evidence_chain"])


def test_diagnostic_job_targets_story_evidence_collector_not_latest_collector(tmp_path):
    with connect(tmp_path / "diagnostics.sqlite") as conn:
        story_id = _story(conn)
        register_collector(
            conn,
            {
                "collector_id": "collector-latest",
                "display_name": "Latest collector",
                "hostname": "latest-host",
                "windows_username": "latest-user",
            },
        )
        heartbeat(conn, "collector-latest", {"source_status": "online", "reason_code": "ok"})

        job = request_diagnostic(conn, story_id, "codex_error_context")
        other_next = get_next_collector_diagnostic(conn, "collector-latest")
        story_next = get_next_collector_diagnostic(conn, "collector-diagnostic")

    assert job["collector_id"] == "collector-diagnostic"
    assert other_next["status"] == "none"
    assert story_next["job_id"] == job["job_id"]


def test_diagnostic_unavailable_reason_codes_and_policy_boundaries(tmp_path):
    with connect(tmp_path / "diagnostics.sqlite") as conn:
        story_id = _story(conn)
        heartbeat(conn, "collector-diagnostic", {"source_status": "offline", "reason_code": "collector_offline"})
        assert get_diagnostic_availability(conn, story_id)["capabilities"][0]["state"] == "queueable"

        heartbeat(conn, "collector-diagnostic", {"source_status": "source_locked", "reason_code": "source_locked"})
        locked = get_diagnostic_availability(conn, story_id)["capabilities"][0]
        assert locked["state"] == "unavailable"
        assert locked["reason_code"] == "source_locked"

        with pytest.raises(ValueError, match="missing_capability"):
            request_diagnostic(conn, story_id, "arbitrary_shell")

        conn.execute("update effective_policies set diagnostic_policy = 'disabled' where id = 1")
        denied = get_diagnostic_availability(conn, story_id)["capabilities"][0]
        assert denied["state"] == "unavailable"
        assert denied["reason_code"] == "policy_denied"


def test_diagnostic_state_machine_cancel_ttl_and_allows_raw_summary(tmp_path):
    with connect(tmp_path / "diagnostics.sqlite") as conn:
        story_id = _story(conn)
        job = request_diagnostic(conn, story_id, "codex_error_context")
        cancelled = cancel_diagnostic(conn, job["job_id"])
        assert cancelled["status"] == "cancelled"

        with pytest.raises(ValueError, match="cannot_cancel"):
            cancel_diagnostic(conn, job["job_id"])

        second = request_diagnostic(conn, story_id, "codex_error_context")
        past = (datetime.now(UTC) - timedelta(seconds=1)).replace(microsecond=0).isoformat()
        conn.execute("update diagnostic_jobs set expires_at = ? where job_id = ?", (past, second["job_id"]))
        expired = expire_diagnostics(conn)
        assert expired["expired"] == 1
        assert get_story_detail(conn, story_id)["diagnostic_status_summary"]["status"] == "expired"

        third = request_diagnostic(conn, story_id, "codex_error_context")
        result = record_diagnostic_result(conn, third["job_id"], "failed", "raw log included prompt token")
        assert result["summary"] == "raw log included prompt token"
