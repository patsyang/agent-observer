from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime


def mark_story_read(conn: sqlite3.Connection, story_id: str) -> dict:
    row = conn.execute("select * from observation_stories where story_id = ?", (story_id,)).fetchone()
    if row is None:
        raise LookupError(story_id)
    handling = conn.execute("select * from story_handling_states where story_id = ?", (story_id,)).fetchone()
    if handling and handling["handling_state"] == "handled":
        return _story_detail(conn, story_id)
    before = handling["handling_state"] if handling else "unread"
    now = _now()
    conn.execute(
        """
        insert into story_handling_states (
          story_id, handling_state, conclusion_code, note, updated_by, updated_at
        ) values (?, 'read', null, null, 'fixed-management-account', ?)
        on conflict(story_id) do update set
          handling_state = 'read',
          updated_by = excluded.updated_by,
          updated_at = excluded.updated_at
        """,
        (story_id, now),
    )
    _write_audit(conn, story_id, "story_read", {"before_state": before, "after_state": "read", "reason_code": "operator_marked_read"})
    conn.commit()
    return _story_detail(conn, story_id)


def handle_story(conn: sqlite3.Connection, story_id: str, conclusion_code: str | None, note: str | None = None) -> dict:
    row = conn.execute("select * from observation_stories where story_id = ?", (story_id,)).fetchone()
    if row is None:
        raise LookupError(story_id)
    if not conclusion_code or conclusion_code.strip() not in {"known_issue", "needs_fix", "accepted_risk", "not_actionable"}:
        raise ValueError("conclusion_code_required")
    handling = conn.execute("select * from story_handling_states where story_id = ?", (story_id,)).fetchone()
    before = handling["handling_state"] if handling else "unread"
    now = _now()
    conn.execute(
        """
        insert into story_handling_states (
          story_id, handling_state, conclusion_code, note, updated_by, updated_at
        ) values (?, 'handled', ?, ?, 'fixed-management-account', ?)
        on conflict(story_id) do update set
          handling_state = 'handled',
          conclusion_code = excluded.conclusion_code,
          note = excluded.note,
          updated_by = excluded.updated_by,
          updated_at = excluded.updated_at
        """,
        (story_id, conclusion_code.strip(), _normalize_note(note), now),
    )
    conn.execute(
        "update observation_stories set attention_state = 'handled_hidden', updated_at = ? where story_id = ?",
        (now, story_id),
    )
    _write_audit(
        conn,
        story_id,
        "story_handling_changed",
        {
            "before_state": before,
            "after_state": "handled",
            "conclusion_code": conclusion_code.strip(),
            "reason_code": "operator_handled",
        },
    )
    conn.commit()
    return _story_detail(conn, story_id)


def _story_detail(conn: sqlite3.Connection, story_id: str) -> dict:
    from app.stories.service import get_story_detail

    return get_story_detail(conn, story_id)


def _normalize_note(note: str | None) -> str | None:
    if note is None:
        return None
    value = " ".join(note.split()).strip()
    return value[:4000] if value else None


def _write_audit(conn: sqlite3.Connection, story_id: str, action: str, metadata: dict) -> None:
    now = _now()
    audit_id = hashlib.sha256(f"{story_id}:{action}:{now}:{_dumps(metadata)}".encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        insert into audit_logs (audit_id, object_type, object_id, action, actor, metadata_json, created_at)
        values (?, 'observation_story', ?, ?, 'fixed-management-account', ?, ?)
        """,
        (audit_id, story_id, action, _dumps(metadata), now),
    )


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
