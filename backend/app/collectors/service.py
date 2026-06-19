from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from app.db.connection import SOURCE_STATUSES
from app.policy import get_effective_policy, write_management_audit

ONLINE_TTL_SECONDS = 90


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _hash_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _row_to_collector(row: sqlite3.Row, now: datetime | None = None, global_policy: dict | None = None) -> dict:
    source_status = row["source_status"]
    reason_code = row["reason_code"]
    if source_status == "online" and _heartbeat_stale(row["last_heartbeat_at"], now):
        source_status = "offline"
        reason_code = "heartbeat_stale"
    raw_override = _nullable_bool(row["raw_upload_enabled"])
    if raw_override is None:
        raw_upload_enabled = bool((global_policy or {}).get("upload_raw", False))
        raw_upload_source = "global_policy"
    else:
        raw_upload_enabled = raw_override
        raw_upload_source = "collector_override"
    return {
        "collector_id": row["collector_id"],
        "display_name": row["display_name"],
        "hostname_hash": row["hostname_hash"],
        "windows_username_hash": row["windows_username_hash"],
        "agent_type": row["agent_type"],
        "agent_version": row["agent_version"],
        "source_status": source_status,
        "reason_code": reason_code,
        "policy_version": row["policy_version"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "outbox_backlog": row["outbox_backlog"],
        "raw_upload_enabled": raw_upload_enabled,
        "raw_upload_override": raw_override is not None,
        "raw_upload_source": raw_upload_source,
    }


def register_collector(conn: sqlite3.Connection, payload: dict) -> dict:
    global_policy = get_effective_policy(conn)
    hostname_hash = payload.get("hostname_hash")
    username_hash = payload.get("windows_username_hash")
    hostname = payload.get("hostname") or payload.get("display_name") or payload.get("collector_id")
    windows_username = payload.get("windows_username") or "local-user"
    collector_id = payload.get("collector_id") or _hash_identity(
        f"{hostname_hash or hostname}:{username_hash or windows_username}:{payload.get('agent_type', 'codex')}"
    )
    now = _now()
    existing = conn.execute(
        "select collector_id from collectors where collector_id = ?", (collector_id,)
    ).fetchone()
    source_status = payload.get("source_status", "policy_not_fetched")
    if source_status not in SOURCE_STATUSES:
        raise ValueError(f"unsupported source_status: {source_status}")
    reason_code = payload.get("reason_code") or source_status
    values = {
        "collector_id": collector_id,
        "display_name": payload.get("display_name") or str(hostname or collector_id),
        "hostname_hash": str(hostname_hash or _hash_identity(str(hostname))),
        "windows_username_hash": str(username_hash or _hash_identity(str(windows_username))),
        "agent_type": payload.get("agent_type", "codex"),
        "agent_version": payload.get("agent_version", "0.1.0"),
        "source_status": source_status,
        "reason_code": reason_code,
        "policy_version": global_policy["policy_version"],
        "last_heartbeat_at": now,
        "outbox_backlog": int(payload.get("outbox_backlog", 0)),
        "created_at": now,
        "updated_at": now,
    }
    if existing:
        conn.execute(
            """
            update collectors
            set display_name = :display_name,
                source_status = :source_status,
                reason_code = :reason_code,
                policy_version = :policy_version,
                last_heartbeat_at = :last_heartbeat_at,
                outbox_backlog = :outbox_backlog,
                updated_at = :updated_at
            where collector_id = :collector_id
            """,
            values,
        )
    else:
        conn.execute(
            """
            insert into collectors (
              collector_id, display_name, hostname_hash, windows_username_hash, agent_type,
              agent_version, source_status, reason_code, policy_version, last_heartbeat_at,
              outbox_backlog, created_at, updated_at
            ) values (
              :collector_id, :display_name, :hostname_hash, :windows_username_hash, :agent_type,
              :agent_version, :source_status, :reason_code, :policy_version, :last_heartbeat_at,
              :outbox_backlog, :created_at, :updated_at
            )
            """,
            values,
        )
    conn.commit()
    return {"collector_id": collector_id, "effective_policy": _collector_policy(conn, collector_id, global_policy)}


def heartbeat(conn: sqlite3.Connection, collector_id: str, payload: dict) -> dict:
    source_status = payload.get("source_status", "online")
    if source_status not in SOURCE_STATUSES:
        raise ValueError(f"unsupported source_status: {source_status}")
    global_policy = get_effective_policy(conn)
    now = _now()
    cursor = conn.execute(
        """
        update collectors
        set source_status = ?,
            reason_code = ?,
            policy_version = ?,
            last_heartbeat_at = ?,
            outbox_backlog = ?,
            updated_at = ?
        where collector_id = ?
        """,
        (
            source_status,
            payload.get("reason_code") or source_status,
            global_policy["policy_version"],
            now,
            int(payload.get("outbox_backlog", 0)),
            now,
            collector_id,
        ),
    )
    if cursor.rowcount == 0:
        raise LookupError(collector_id)
    conn.commit()
    return {"collector_id": collector_id, "effective_policy": _collector_policy(conn, collector_id, global_policy)}


def list_collectors(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "select * from collectors order by last_heartbeat_at desc, collector_id"
    ).fetchall()
    now = datetime.now(UTC)
    global_policy = get_effective_policy(conn)
    return [_row_to_collector(row, now, global_policy) for row in rows]


def update_collector_display_name(conn: sqlite3.Connection, collector_id: str, display_name: str) -> dict:
    clean_name = " ".join(display_name.split()).strip()
    if not clean_name:
        raise ValueError("display_name_required")
    if any(term in clean_name.lower() for term in ("raw log", "prompt", "token", "auth", "file content")):
        raise ValueError("display_name_contains_prohibited_raw_content")
    row = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    if row is None:
        raise LookupError(collector_id)
    now = _now()
    conn.execute(
        "update collectors set display_name = ?, updated_at = ? where collector_id = ?",
        (clean_name[:80], now, collector_id),
    )
    write_management_audit(
        conn,
        "collector",
        collector_id,
        "display_label_changed",
        {"before_label": row["display_name"], "after_label": clean_name[:80], "reason_code": "operator_label_update"},
    )
    conn.commit()
    updated = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    return _row_to_collector(updated, global_policy=get_effective_policy(conn))


def update_collector_raw_upload(conn: sqlite3.Connection, collector_id: str, enabled: bool) -> dict:
    row = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    if row is None:
        raise LookupError(collector_id)
    current = _row_to_collector(row)
    if current["source_status"] != "online":
        raise ValueError("collector_not_online")
    now = _now()
    conn.execute(
        "update collectors set raw_upload_enabled = ?, updated_at = ? where collector_id = ?",
        (1 if enabled else 0, now, collector_id),
    )
    write_management_audit(
        conn,
        "collector",
        collector_id,
        "raw_upload_policy_changed",
        {"raw_upload_enabled": bool(enabled), "reason_code": "operator_raw_upload_update"},
    )
    conn.commit()
    updated = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    return _row_to_collector(updated, global_policy=get_effective_policy(conn))


def delete_collector(conn: sqlite3.Connection, collector_id: str) -> dict:
    row = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    if row is None:
        raise LookupError(collector_id)
    conn.execute("delete from collectors where collector_id = ?", (collector_id,))
    write_management_audit(
        conn,
        "collector",
        collector_id,
        "collector_removed",
        {
            "before_label": row["display_name"],
            "source_status": row["source_status"],
            "reason_code": "operator_cleanup",
        },
    )
    conn.commit()
    return {"collector_id": collector_id, "removed": True, "reason_code": "operator_cleanup"}


def _heartbeat_stale(value: str | None, now: datetime | None = None) -> bool:
    if not value:
        return True
    try:
        heartbeat_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return (current - heartbeat_at.astimezone(UTC)).total_seconds() > ONLINE_TTL_SECONDS


def _collector_policy(conn: sqlite3.Connection, collector_id: str, global_policy: dict | None = None) -> dict:
    policy = dict(global_policy or get_effective_policy(conn))
    row = conn.execute("select raw_upload_enabled from collectors where collector_id = ?", (collector_id,)).fetchone()
    override = _nullable_bool(row["raw_upload_enabled"]) if row else None
    if override is None:
        policy["raw_upload_source"] = "global_policy"
    else:
        policy["upload_raw"] = override
        policy["raw_upload_source"] = "collector_override"
    policy["raw_upload_enabled"] = bool(policy["upload_raw"])
    return policy


def _nullable_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)
