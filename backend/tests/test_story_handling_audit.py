from __future__ import annotations

import json

import pytest

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.stories.service import get_story_detail, handle_story, list_stories, mark_story_read, rebuild_stories


def _story_batch(batch_id: str = "batch-handling-001", summary: str = "Checkout workflow failed repeatedly") -> dict:
    return {
        "batch_id": batch_id,
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": f"cursor-{batch_id}",
        "items": [
            {
                "source_event_id": f"{batch_id}-error",
                "fact_type": "error",
                "category": "codex_error",
                "quality": "high",
                "severity": "high",
                "summary": summary,
                "occurred_at": "2026-06-18T10:00:00+00:00",
                "span": "command:checkout",
                "raw_hash": f"hash-{batch_id}",
                "projection": {"impact": "checkout workflow"},
                "error_signature": {"signature_key": "sig-handling-checkout", "category": "codex_error"},
                "source_refs": {"conversation_ref": "conversation-handling"},
                "source_specific": {"codex_event_type": "tool_result"},
            }
        ],
    }


def test_handle_story_requires_structured_conclusion_and_writes_audit(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _story_batch())
        story_id = rebuild_stories(conn, reason="initial")["stories"][0]["story_id"]

        with pytest.raises(ValueError, match="conclusion_code_required"):
            handle_story(conn, story_id, None, "Reviewed")

        read_detail = mark_story_read(conn, story_id)
        handled = handle_story(conn, story_id, "known_issue", "Tracked in backlog")
        queue = list_stories(conn)
        hidden_queue = list_stories(conn, include_hidden=True)
        audits = conn.execute("select * from audit_logs where object_id = ? order by created_at", (story_id,)).fetchall()

    assert read_detail["handling_state"] == "read"
    assert handled["handling_state"] == "handled"
    assert handled["attention_state"] == "handled_hidden"
    assert handled["conclusion_code"] == "known_issue"
    assert handled["handling_note"] == "Tracked in backlog"
    assert handled["recent_audit_summary"]["latest"].startswith("story_handling_changed by fixed-management-account")
    assert queue["stories"] == []
    assert hidden_queue["stories"][0]["story_id"] == story_id
    assert [row["action"] for row in audits] == ["story_read", "story_handling_changed"]
    assert json.loads(audits[-1]["metadata_json"]) == {
        "after_state": "handled",
        "before_state": "read",
        "conclusion_code": "known_issue",
        "reason_code": "operator_handled",
    }


def test_rebuild_preserves_handling_and_recurrence_returns_needs_review(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _story_batch())
        story_id = rebuild_stories(conn, reason="initial")["stories"][0]["story_id"]
        handle_story(conn, story_id, "needs_fix", "Owner assigned")

        ingest_telemetry(conn, _story_batch("batch-handling-002", "Checkout workflow failed with new evidence"))
        recurrent = rebuild_stories(conn, reason="recurrence")["stories"][0]
        detail = get_story_detail(conn, story_id)

    assert recurrent["attention_state"] == "needs_review"
    assert detail["handling_state"] == "handled"
    assert detail["conclusion_code"] == "needs_fix"
    assert detail["handling_note"] == "Owner assigned"


def test_rebuild_reason_change_does_not_reopen_handled_story(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _story_batch())
        story_id = rebuild_stories(conn, reason="initial")["stories"][0]["story_id"]
        handle_story(conn, story_id, "known_issue", "Owner assigned")

        rebuild_stories(conn, reason="scheduled-refresh")
        queue = list_stories(conn)
        detail = get_story_detail(conn, story_id)

    assert queue["stories"] == []
    assert detail["attention_state"] == "handled_hidden"
    assert detail["conclusion_code"] == "known_issue"


def test_handling_note_allows_raw_operator_context(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _story_batch())
        story_id = rebuild_stories(conn, reason="initial")["stories"][0]["story_id"]

        handled = handle_story(conn, story_id, "known_issue", "raw log contained prompt and token data")

    assert handled["handling_note"] == "raw log contained prompt and token data"
