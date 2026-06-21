from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from app.collector_client.version import COLLECTOR_CLIENT_VERSION, COLLECTOR_PROTOCOL_VERSION
from app.db.connection import SOURCE_STATUSES
from app.policy import get_effective_policy, write_management_audit

ONLINE_TTL_SECONDS = 240
RUNTIME_PHASES = {"starting", "idle", "collecting", "uploading", "waiting", "backfilling", "stopping"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _hash_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _row_to_collector(row: sqlite3.Row, now: datetime | None = None, global_policy: dict | None = None) -> dict:
    source_status = _normalize_source_status(row["source_status"])
    reason_code = row["reason_code"]
    if source_status == "online" and _heartbeat_stale(row["last_heartbeat_at"], now):
        source_status = "offline"
        reason_code = "heartbeat_stale"
    return {
        "collector_id": row["collector_id"],
        "display_name": row["display_name"],
        "hostname_hash": row["hostname_hash"],
        "windows_username_hash": row["windows_username_hash"],
        "agent_type": row["agent_type"],
        "protocol_version": row["protocol_version"],
        "agent_version": row["agent_version"],
        "source_status": source_status,
        "reason_code": reason_code,
        "policy_version": row["policy_version"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "last_seen_at": row["last_seen_at"] or row["last_heartbeat_at"],
        "runtime_phase": row["runtime_phase"],
        "last_cycle_duration_ms": row["last_cycle_duration_ms"],
        "last_error": row["last_error"],
        "outbox_backlog": row["outbox_backlog"],
    }


def register_collector(conn: sqlite3.Connection, payload: dict) -> dict:
    protocol_version, agent_version = _collector_protocol(payload)
    global_policy = get_effective_policy(conn)
    hostname_hash = payload.get("hostname_hash")
    username_hash = payload.get("windows_username_hash")
    hostname = payload.get("hostname") or payload.get("display_name") or payload.get("collector_id")
    windows_username = payload.get("windows_username") or "local-user"
    collector_id = payload.get("collector_id") or _hash_identity(
        f"{hostname_hash or hostname}:{username_hash or windows_username}:{payload.get('agent_type', 'codex')}"
    )
    now = _now()
    existing = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    source_status = _source_status_from_payload(payload, existing)
    reason_code = _reason_from_payload(payload, existing, source_status)
    runtime_phase = _runtime_phase(payload.get("runtime_phase") or (existing["runtime_phase"] if existing else "idle"))
    values = {
        "collector_id": collector_id,
        "display_name": payload.get("display_name") or str(hostname or collector_id),
        "hostname_hash": str(hostname_hash or _hash_identity(str(hostname))),
        "windows_username_hash": str(username_hash or _hash_identity(str(windows_username))),
        "agent_type": payload.get("agent_type", "codex"),
        "protocol_version": protocol_version,
        "agent_version": agent_version,
        "source_status": source_status,
        "reason_code": reason_code,
        "runtime_phase": runtime_phase,
        "policy_version": global_policy["policy_version"],
        "last_heartbeat_at": now,
        "last_seen_at": now,
        "last_cycle_duration_ms": _nullable_int(payload.get("last_cycle_duration_ms")),
        "last_error": payload.get("last_error"),
        "outbox_backlog": int(payload.get("outbox_backlog", 0)),
        "created_at": now,
        "updated_at": now,
    }
    if existing:
        conn.execute(
            """
            update collectors
            set display_name = :display_name,
                protocol_version = :protocol_version,
                agent_version = :agent_version,
                source_status = :source_status,
                reason_code = :reason_code,
                runtime_phase = :runtime_phase,
                policy_version = :policy_version,
                last_heartbeat_at = :last_heartbeat_at,
                last_seen_at = :last_seen_at,
                last_cycle_duration_ms = coalesce(:last_cycle_duration_ms, last_cycle_duration_ms),
                last_error = :last_error,
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
              protocol_version, agent_version, source_status, reason_code, policy_version, last_heartbeat_at,
              runtime_phase, last_seen_at, last_cycle_duration_ms, last_error,
              outbox_backlog, created_at, updated_at
            ) values (
              :collector_id, :display_name, :hostname_hash, :windows_username_hash, :agent_type,
              :protocol_version, :agent_version, :source_status, :reason_code, :policy_version, :last_heartbeat_at,
              :runtime_phase, :last_seen_at, :last_cycle_duration_ms, :last_error,
              :outbox_backlog, :created_at, :updated_at
            )
            """,
            values,
        )
    conn.commit()
    return {"collector_id": collector_id, "effective_policy": _collector_policy(conn, collector_id, global_policy)}


def _collector_protocol(payload: dict) -> tuple[str, str]:
    protocol = payload.get("protocol_version")
    if protocol != COLLECTOR_PROTOCOL_VERSION:
        raise ValueError("unsupported_collector_protocol")
    version = payload.get("agent_version")
    if version != COLLECTOR_CLIENT_VERSION:
        raise ValueError("unsupported_collector_version")
    return str(protocol), str(version)


def heartbeat(conn: sqlite3.Connection, collector_id: str, payload: dict) -> dict:
    protocol_version, agent_version = _collector_protocol(payload)
    source_status = payload.get("source_status", "online")
    source_status = _normalize_source_status(source_status)
    if source_status not in SOURCE_STATUSES:
        raise ValueError(f"unsupported source_status: {source_status}")
    runtime_phase = _runtime_phase(payload.get("runtime_phase", "idle"))
    global_policy = get_effective_policy(conn)
    now = _now()
    cursor = conn.execute(
        """
        update collectors
        set source_status = ?,
            protocol_version = ?,
            agent_version = ?,
            reason_code = ?,
            runtime_phase = ?,
            policy_version = ?,
            last_heartbeat_at = ?,
            last_seen_at = ?,
            last_cycle_duration_ms = ?,
            last_error = ?,
            outbox_backlog = ?,
            updated_at = ?
        where collector_id = ?
        """,
        (
            source_status,
            protocol_version,
            agent_version,
            payload.get("reason_code") or source_status,
            runtime_phase,
            global_policy["policy_version"],
            now,
            now,
            _nullable_int(payload.get("last_cycle_duration_ms")),
            payload.get("last_error"),
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
    return dict(global_policy or get_effective_policy(conn))


def _normalize_source_status(value: object) -> str:
    status = str(value or "online")
    if status in SOURCE_STATUSES:
        return status
    if status == "policy_not_fetched":
        return "degraded"
    if status in {"state_corrupt", "outbox_backlog"}:
        return "degraded"
    return status


def _source_status_from_payload(payload: dict, existing: sqlite3.Row | None) -> str:
    incoming = payload.get("source_status")
    if incoming is None:
        return _normalize_source_status(existing["source_status"]) if existing else "online"
    status = _normalize_source_status(incoming)
    if status not in SOURCE_STATUSES:
        raise ValueError(f"unsupported source_status: {incoming}")
    if existing and incoming == "policy_not_fetched":
        return _normalize_source_status(existing["source_status"])
    return status


def _reason_from_payload(payload: dict, existing: sqlite3.Row | None, source_status: str) -> str:
    incoming = payload.get("source_status")
    reason = payload.get("reason_code")
    if existing and incoming == "policy_not_fetched":
        return existing["reason_code"] or "policy_stale"
    if reason == "policy_not_fetched":
        return "policy_stale"
    return reason or source_status


def _runtime_phase(value: object) -> str:
    phase = str(value or "idle")
    return phase if phase in RUNTIME_PHASES else "idle"


def _nullable_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
