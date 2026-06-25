from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.processing.jobs import enqueue_global_signal_rebuild, enqueue_processing_job, processing_status, run_next_job


def _failure_batch() -> dict:
    return {
        "batch_id": "batch-processing",
        "protocol_version": "agent-observer-telemetry/v3",
        "agent_version": "0.3.0",
        "collector_id": "collector-codex",
        "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
        "cursor": "cursor",
        "items": [
            {
                "source_event_id": "tool-failure-processing",
                "fact_type": "error",
                "category": "tool_execution_failure",
                "quality": "high",
                "severity": "high",
                "summary": "function_call_output failed with exit_code=1",
                "occurred_at": "2026-06-18T10:00:00+00:00",
                "span": "event:tool-failure-processing",
                "raw_hash": "hash-tool-failure-processing",
                "projection": {"tool_name": "exec_command", "exit_code": 1},
                "error_signature": {
                    "signature_key": "tool_execution_failure:exec_command:processing:1",
                    "category": "tool_execution_failure",
                },
                "source_refs": {"conversation_ref": "conversation-processing"},
                "source_specific": {"event_type": "tool_result"},
            }
        ],
    }


def test_processing_job_updates_signal_and_status(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest = ingest_telemetry(conn, _failure_batch())
        before = processing_status(conn)
        result = run_next_job(conn, reason="test")
        after = processing_status(conn)
        signal_count = conn.execute("select count(*) from behavior_signals").fetchone()[0]

    assert ingest["processing_jobs_queued"] == 1
    assert before["state"] == "pending"
    assert result["status"] == "processed"
    assert after["state"] == "idle"
    assert after["counts"]["succeeded"] == 1
    assert signal_count == 1


def test_processing_job_merge_and_retry_failure(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        first = enqueue_processing_job(conn, job_type="behavior_signal_update", scope_type="unsupported", scope_id="bad")
        second = enqueue_processing_job(conn, job_type="behavior_signal_update", scope_type="unsupported", scope_id="bad")
        conn.commit()
        for _ in range(3):
            result = run_next_job(conn, reason="test")
        row = conn.execute("select status, attempts, last_error from processing_jobs where job_id = ?", (first["job_id"],)).fetchone()

    assert first == second
    assert result["status"] == "failed"
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert row["last_error"] == "ValueError"


def test_stale_running_job_is_recovered_and_processed(tmp_path):
    stale_started_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _failure_batch())
        conn.execute(
            """
            update processing_jobs
            set status = 'running', started_at = ?, updated_at = ?
            """,
            (stale_started_at, stale_started_at),
        )
        conn.commit()
        result = run_next_job(conn, reason="test")
        row = conn.execute("select status, attempts from processing_jobs").fetchone()

    assert result["status"] == "processed"
    assert row["status"] == "succeeded"
    assert row["attempts"] == 1


def test_global_rebuild_is_queued_not_executed_synchronously(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        queued = enqueue_global_signal_rebuild(conn, reason="api")
        status = processing_status(conn)
        signal_count = conn.execute("select count(*) from behavior_signals").fetchone()[0]

    assert queued["job_id"] == "behavior_signal_rebuild:global:all"
    assert queued["status"] == "queued"
    assert status["state"] == "pending"
    assert signal_count == 0
