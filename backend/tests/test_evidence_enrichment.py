from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.collectors.service import heartbeat, register_collector
from app.db.connection import connect
from app.evidence_enrichment.service import (
    cancel_enrichment,
    expire_enrichments,
    get_enrichment_availability,
    get_next_collector_enrichment,
    record_enrichment_result,
    record_collector_enrichment_result,
    request_enrichment,
)
from app.ingest.service import ingest_telemetry
from app.stories.service import get_story_detail, rebuild_stories

CLIENT_PROTOCOL = {
    "protocol_version": "agent-observer-telemetry/v2",
    "agent_version": "0.2.0",
}


def _batch(batch_id: str = "batch-enrichment-001") -> dict:
    return {
        "batch_id": batch_id,
        "protocol_version": "agent-observer-telemetry/v2",
        "agent_version": "0.2.0",
        "collector_id": "collector-enrichment",
        "source": "codex",
        "cursor": f"cursor-{batch_id}",
        "items": [
            {
                "source_event_id": f"{batch_id}-error",
                "fact_type": "error",
                "category": "codex_error",
                "quality": "high",
                "severity": "high",
                "summary": "Enrichment fixture command failed",
                "occurred_at": "2026-06-18T12:00:00+00:00",
                "span": "conversation:enrichment",
                "raw_hash": f"hash-{batch_id}-error",
                "projection": {"signature_key": "sig-enrichment-fixture"},
                "error_signature": {"signature_key": "sig-enrichment-fixture", "category": "codex_error"},
                "source_refs": {"conversation_ref": "conversation-enrichment", "source_path_hash": "fixture-path", "line": 7},
            }
        ],
    }


def _story(conn) -> str:
    register_collector(
        conn,
        {
            "collector_id": "collector-enrichment",
            "display_name": "Enrichment collector",
            "hostname": "enrichment-host",
            "windows_username": "enrichment-user",
            **CLIENT_PROTOCOL,
        },
    )
    heartbeat(conn, "collector-enrichment", {**CLIENT_PROTOCOL, "source_status": "online", "reason_code": "ok"})
    ingest_telemetry(conn, _batch())
    return rebuild_stories(conn, reason="enrichment-test")["stories"][0]["story_id"]


def test_enrichment_success_updates_evidence_chain_and_audit(tmp_path):
    with connect(tmp_path / "enrichments.sqlite") as conn:
        story_id = _story(conn)

        availability = get_enrichment_availability(conn, story_id)
        assert availability["capabilities"][0]["state"] == "available"

        job = request_enrichment(conn, story_id, "codex_tool_failure_context")
        assert job["status"] == "pending"
        assert job["command"]["command_id"] == "collect_codex_tool_failure_context"
        assert job["command"]["capability_id"] == "codex_tool_failure_context"
        assert job["command"]["story_id"] == story_id
        assert job["command"]["evidence_refs"][0]["conversation_ref"] == "conversation-enrichment"
        assert job["command"]["evidence_refs"][0]["source_line"] == 7
        assert "shell" not in job["command"]
        assert "template" not in job["command"]
        assert "output_schema" not in job["command"]
        assert request_enrichment(conn, story_id, "codex_tool_failure_context")["job_id"] == job["job_id"]
        assert conn.execute("select count(*) from enrichment_jobs where story_id = ?", (story_id,)).fetchone()[0] == 1

        result = record_enrichment_result(conn, job["job_id"], "succeeded", "Sanitized stack category matched")
        detail = get_story_detail(conn, story_id)
        rebuilt_detail = get_story_detail(conn, rebuild_stories(conn, reason="after-enrichment")["stories"][0]["story_id"])
        audits = conn.execute("select action from audit_logs where object_id = ? order by rowid", (story_id,)).fetchall()

    assert result["status"] == "succeeded"
    assert detail["enrichment_status_summary"]["status"] == "succeeded"
    assert any(entry["category"] == "enrichment_result" for entry in detail["current_snapshot"]["evidence_chain"])
    assert rebuilt_detail["enrichment_status_summary"]["status"] == "succeeded"
    assert any(entry["category"] == "enrichment_result" for entry in rebuilt_detail["current_snapshot"]["evidence_chain"])
    assert detail["handling_state"] == "unread"
    assert [row["action"] for row in audits] == ["enrichment_requested", "enrichment_result_recorded"]


def test_collector_pulls_enabled_enrichment_and_returns_result(tmp_path):
    with connect(tmp_path / "enrichments.sqlite") as conn:
        story_id = _story(conn)
        job = request_enrichment(conn, story_id, "codex_tool_failure_context")

        next_job = get_next_collector_enrichment(conn, "collector-enrichment")
        assert next_job["job_id"] == job["job_id"]
        assert next_job["status"] == "running"
        assert next_job["command"]["command_id"] == "collect_codex_tool_failure_context"
        assert "shell" not in next_job["command"]
        assert "template" not in next_job["command"]

        result = record_collector_enrichment_result(
            conn,
            "collector-enrichment",
            job["job_id"],
            {"status": "succeeded", "summary": "错误上下文已匹配", "projection": {"matched_category": "codex_error"}},
        )
        detail = get_story_detail(conn, story_id)

    assert result["status"] == "succeeded"
    assert detail["enrichment_status_summary"]["status"] == "succeeded"
    assert any(entry["category"] == "enrichment_result" for entry in detail["current_snapshot"]["evidence_chain"])


def test_enrichment_job_targets_story_evidence_collector_not_latest_collector(tmp_path):
    with connect(tmp_path / "enrichments.sqlite") as conn:
        story_id = _story(conn)
        register_collector(
            conn,
            {
                "collector_id": "collector-latest",
                "display_name": "Latest collector",
                "hostname": "latest-host",
                "windows_username": "latest-user",
                **CLIENT_PROTOCOL,
            },
        )
        heartbeat(conn, "collector-latest", {**CLIENT_PROTOCOL, "source_status": "online", "reason_code": "ok"})

        job = request_enrichment(conn, story_id, "codex_tool_failure_context")
        other_next = get_next_collector_enrichment(conn, "collector-latest")
        story_next = get_next_collector_enrichment(conn, "collector-enrichment")

    assert job["collector_id"] == "collector-enrichment"
    assert other_next["status"] == "none"
    assert story_next["job_id"] == job["job_id"]


def test_enrichment_unavailable_reason_codes_and_policy_boundaries(tmp_path):
    with connect(tmp_path / "enrichments.sqlite") as conn:
        story_id = _story(conn)
        heartbeat(
            conn,
            "collector-enrichment",
            {**CLIENT_PROTOCOL, "source_status": "offline", "reason_code": "collector_offline"},
        )
        assert get_enrichment_availability(conn, story_id)["capabilities"][0]["state"] == "queueable"

        heartbeat(
            conn,
            "collector-enrichment",
            {**CLIENT_PROTOCOL, "source_status": "source_locked", "reason_code": "source_locked"},
        )
        locked = get_enrichment_availability(conn, story_id)["capabilities"][0]
        assert locked["state"] == "unavailable"
        assert locked["reason_code"] == "source_locked"

        with pytest.raises(ValueError, match="missing_capability"):
            request_enrichment(conn, story_id, "arbitrary_shell")

        conn.execute("update effective_policies set enrichment_mode = 'disabled' where id = 1")
        denied = get_enrichment_availability(conn, story_id)["capabilities"][0]
        assert denied["state"] == "unavailable"
        assert denied["reason_code"] == "policy_denied"


def test_enrichment_state_machine_cancel_ttl_and_allows_raw_summary(tmp_path):
    with connect(tmp_path / "enrichments.sqlite") as conn:
        story_id = _story(conn)
        job = request_enrichment(conn, story_id, "codex_tool_failure_context")
        cancelled = cancel_enrichment(conn, job["job_id"])
        assert cancelled["status"] == "cancelled"

        with pytest.raises(ValueError, match="cannot_cancel"):
            cancel_enrichment(conn, job["job_id"])

        second = request_enrichment(conn, story_id, "codex_tool_failure_context")
        past = (datetime.now(UTC) - timedelta(seconds=1)).replace(microsecond=0).isoformat()
        conn.execute("update enrichment_jobs set expires_at = ? where job_id = ?", (past, second["job_id"]))
        availability = get_enrichment_availability(conn, story_id)
        assert availability["active_job"] is None
        assert get_story_detail(conn, story_id)["enrichment_status_summary"]["status"] == "expired"

        third = request_enrichment(conn, story_id, "codex_tool_failure_context")
        result = record_enrichment_result(conn, third["job_id"], "failed", "raw log included prompt token")
        assert result["summary"] == "raw log included prompt token"
