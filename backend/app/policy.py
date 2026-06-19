from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime


MANAGEMENT_ACTOR = "fixed-management-account"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def get_effective_policy(conn: sqlite3.Connection) -> dict:
    row = conn.execute("select * from effective_policies where id = 1").fetchone()
    return {
        "policy_version": row["policy_version"],
        "template_enabled": bool(row["template_enabled"]),
        "upload_raw": bool(row["upload_raw"]),
        "collection_policy": row["collection_policy"],
        "diagnostic_policy": row["diagnostic_policy"],
    }


def update_effective_policy(conn: sqlite3.Connection, payload: dict) -> dict:
    current = get_effective_policy(conn)
    expected_version = payload.get("expected_version")
    if expected_version is None:
        raise ValueError("expected_version_required")
    if int(expected_version) != current["policy_version"]:
        raise ValueError("policy_version_conflict")

    next_policy = {
        "policy_version": current["policy_version"] + 1,
        "template_enabled": bool(payload.get("template_enabled", current["template_enabled"])),
        "upload_raw": bool(payload.get("upload_raw", current["upload_raw"])),
        "collection_policy": _clean_policy_text(payload.get("collection_policy", current["collection_policy"])),
        "diagnostic_policy": _clean_policy_text(payload.get("diagnostic_policy", current["diagnostic_policy"])),
    }
    conn.execute(
        """
        update effective_policies
        set policy_version = ?,
            template_enabled = ?,
            upload_raw = ?,
            collection_policy = ?,
            diagnostic_policy = ?
        where id = 1
        """,
        (
            next_policy["policy_version"],
            int(next_policy["template_enabled"]),
            int(next_policy["upload_raw"]),
            next_policy["collection_policy"],
            next_policy["diagnostic_policy"],
        ),
    )
    _write_audit(
        conn,
        "policy",
        "effective_policy",
        "policy_changed",
        {
            "before_version": current["policy_version"],
            "after_version": next_policy["policy_version"],
            "template_enabled": next_policy["template_enabled"],
            "upload_raw": next_policy["upload_raw"],
            "reason_code": "operator_policy_update",
        },
    )
    conn.commit()
    return next_policy


def recent_audit(conn: sqlite3.Connection, limit: int = 5) -> dict:
    rows = conn.execute(
        "select object_type, object_id, action, actor, metadata_json, created_at from audit_logs order by rowid desc limit ?",
        (limit,),
    ).fetchall()
    events = [
        {
            "object_type": row["object_type"],
            "object_id": row["object_id"],
            "action": row["action"],
            "actor": row["actor"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    latest = events[0] if events else None
    return {
        "latest": f"{latest['action']} by {latest['actor']} at {latest['created_at']}" if latest else "暂无审计记录",
        "events": events,
    }


def write_management_audit(conn: sqlite3.Connection, object_type: str, object_id: str, action: str, metadata: dict) -> None:
    _write_audit(conn, object_type, object_id, action, metadata)


def _clean_policy_text(value: object) -> str:
    text = " ".join(str(value).split()).strip()
    if not text:
        raise ValueError("policy_text_required")
    return text[:240]


def _write_audit(conn: sqlite3.Connection, object_type: str, object_id: str, action: str, metadata: dict) -> None:
    now = _now()
    metadata_json = json.dumps(metadata, sort_keys=True)
    audit_id = hashlib.sha256(f"{object_type}:{object_id}:{action}:{now}:{metadata_json}".encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        insert into audit_logs (audit_id, object_type, object_id, action, actor, metadata_json, created_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (audit_id, object_type, object_id, action, MANAGEMENT_ACTOR, metadata_json, now),
    )
