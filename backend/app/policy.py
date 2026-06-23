from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime


MANAGEMENT_ACTOR = "fixed-management-account"
DEFAULT_COLLECTION_INTERVAL_SECONDS = 5
DEFAULT_MAX_EVENTS_PER_CYCLE = 500
DEFAULT_UPLOAD_BATCH_SIZE = 100


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def get_effective_policy(conn: sqlite3.Connection) -> dict:
    row = conn.execute("select * from effective_policies where id = 1").fetchone()
    return {
        "policy_version": row["policy_version"],
        "raw_upload_mode": "always_on",
        "enrichment_mode": row["enrichment_mode"],
        "collection_interval_seconds": row["collection_interval_seconds"],
        "max_events_per_cycle": row["max_events_per_cycle"],
        "upload_batch_size": row["upload_batch_size"],
    }


def update_effective_policy(conn: sqlite3.Connection, payload: dict) -> dict:
    current = get_effective_policy(conn)
    expected_version = payload.get("expected_version")
    if expected_version is None:
        raise ValueError("expected_version_required")
    if int(expected_version) != current["policy_version"]:
        raise ValueError("policy_version_conflict")
    if extra_fields := set(payload) - {
        "expected_version",
        "enrichment_mode",
        "collection_interval_seconds",
        "max_events_per_cycle",
        "upload_batch_size",
    }:
        raise ValueError(f"unsupported_policy_field:{sorted(extra_fields)[0]}")

    next_policy = {
        "policy_version": current["policy_version"] + 1,
        "raw_upload_mode": "always_on",
        "enrichment_mode": _enrichment_mode(payload.get("enrichment_mode", current["enrichment_mode"])),
        "collection_interval_seconds": _bounded_int(
            payload.get("collection_interval_seconds", current["collection_interval_seconds"]),
            "collection_interval_seconds",
            1,
            300,
        ),
        "max_events_per_cycle": _bounded_int(
            payload.get("max_events_per_cycle", current["max_events_per_cycle"]),
            "max_events_per_cycle",
            100,
            5000,
        ),
        "upload_batch_size": _bounded_int(
            payload.get("upload_batch_size", current["upload_batch_size"]),
            "upload_batch_size",
            20,
            500,
        ),
    }
    conn.execute(
        """
        update effective_policies
        set policy_version = ?,
            enrichment_mode = ?,
            collection_interval_seconds = ?,
            max_events_per_cycle = ?,
            upload_batch_size = ?
        where id = 1
        """,
        (
            next_policy["policy_version"],
            next_policy["enrichment_mode"],
            next_policy["collection_interval_seconds"],
            next_policy["max_events_per_cycle"],
            next_policy["upload_batch_size"],
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
            "raw_upload_mode": next_policy["raw_upload_mode"],
            "enrichment_mode": next_policy["enrichment_mode"],
            "collection_interval_seconds": next_policy["collection_interval_seconds"],
            "max_events_per_cycle": next_policy["max_events_per_cycle"],
            "upload_batch_size": next_policy["upload_batch_size"],
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
        "latest": _audit_summary(latest) if latest else "暂无审计记录",
        "events": events,
    }


def _audit_summary(event: dict) -> str:
    labels = {
        "policy_changed": "接入策略已保存",
        "display_label_changed": "采集器显示名已更新",
        "collector_removed": "采集器已移除",
    }
    action = labels.get(str(event.get("action")), "策略记录已更新")
    return f"{action}，时间 {event['created_at']}"


def write_management_audit(conn: sqlite3.Connection, object_type: str, object_id: str, action: str, metadata: dict) -> None:
    _write_audit(conn, object_type, object_id, action, metadata)


def _enrichment_mode(value: object) -> str:
    mode = str(value or "").strip()
    if mode not in {"disabled", "enabled"}:
        raise ValueError("unsupported_enrichment_mode")
    return mode


def _bounded_int(value: object, field: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported_{field}") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field}_out_of_range")
    return parsed


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
