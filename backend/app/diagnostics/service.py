from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta


MANIFEST = {
    "codex_error_context": {
        "label": "Collect Codex error context",
        "command_id": "collect_codex_error_context",
        "template": "codex.error_context.v1",
    }
}
TERMINAL_STATUSES = {"succeeded", "failed", "expired", "unavailable", "cancelled"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _loads(value: str) -> dict:
    return json.loads(value or "{}")


def get_diagnostic_availability(conn: sqlite3.Connection, story_id: str) -> dict:
    _story_row(conn, story_id)
    active_job = _active_job(conn, story_id)
    return {
        "story_id": story_id,
        "active_job": active_job,
        "capabilities": [_capability_state(conn, story_id, capability_id) for capability_id in MANIFEST],
    }


def request_diagnostic(conn: sqlite3.Connection, story_id: str, capability_id: str) -> dict:
    if capability_id not in MANIFEST:
        raise ValueError("missing_capability")
    _story_row(conn, story_id)
    capability = _capability_state(conn, story_id, capability_id)
    if capability["state"] == "unavailable":
        raise ValueError(capability["reason_code"] or "diagnostic_unavailable")
    status = "queued" if capability["state"] == "queueable" else "pending"
    now = _now()
    expires_at = (datetime.now(UTC) + timedelta(minutes=15)).replace(microsecond=0).isoformat()
    command = _command(conn, story_id, capability_id)
    collector_id = _collector_id(conn, story_id)
    job_count = conn.execute("select count(*) from diagnostic_jobs where story_id = ?", (story_id,)).fetchone()[0]
    job_id = hashlib.sha256(f"{story_id}:{capability_id}:{now}:{job_count}".encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        insert into diagnostic_jobs (
          job_id, story_id, collector_id, capability_id, status, command_json, reason_code,
          requested_by, requested_at, expires_at, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, 'fixed-management-account', ?, ?, ?)
        """,
        (
            job_id,
            story_id,
            collector_id,
            capability_id,
            status,
            _dumps(command),
            capability["reason_code"],
            now,
            expires_at,
            now,
        ),
    )
    _update_story_diagnostic(conn, story_id, status, capability["reason_code"])
    _write_audit(
        conn,
        story_id,
        "diagnostic_requested",
        {"capability_id": capability_id, "job_id": job_id, "after_status": status, "reason_code": capability["reason_code"]},
    )
    conn.commit()
    return _job_payload(conn, job_id)


def get_next_collector_diagnostic(conn: sqlite3.Connection, collector_id: str) -> dict:
    collector = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    if collector is None:
        raise LookupError(collector_id)
    now = _now()
    row = conn.execute(
        """
        select * from diagnostic_jobs
        where status in ('pending', 'queued')
          and (collector_id is null or collector_id = ?)
          and expires_at >= ?
        order by requested_at, job_id
        limit 1
        """,
        (collector_id, now),
    ).fetchone()
    if row is None:
        return {"status": "none", "collector_id": collector_id}
    conn.execute(
        "update diagnostic_jobs set status = 'running', collector_id = ?, updated_at = ? where job_id = ?",
        (collector_id, now, row["job_id"]),
    )
    _update_story_diagnostic(conn, row["story_id"], "running", None)
    _write_audit(conn, row["story_id"], "diagnostic_started", {"job_id": row["job_id"], "collector_id": collector_id})
    conn.commit()
    return _job_payload(conn, row["job_id"])


def record_collector_diagnostic_result(conn: sqlite3.Connection, collector_id: str, job_id: str, payload: dict) -> dict:
    job = _job_row(conn, job_id)
    if job["collector_id"] and job["collector_id"] != collector_id:
        raise ValueError("collector_mismatch")
    return record_diagnostic_result(
        conn,
        job_id,
        payload.get("status", ""),
        payload.get("summary", ""),
        payload.get("projection"),
    )


def cancel_diagnostic(conn: sqlite3.Connection, job_id: str) -> dict:
    job = _job_row(conn, job_id)
    if job["status"] not in {"pending", "queued"}:
        raise ValueError("cannot_cancel")
    now = _now()
    conn.execute("update diagnostic_jobs set status = 'cancelled', updated_at = ? where job_id = ?", (now, job_id))
    _update_story_diagnostic(conn, job["story_id"], "cancelled", "operator_cancelled")
    _write_audit(
        conn,
        job["story_id"],
        "diagnostic_cancelled",
        {"job_id": job_id, "capability_id": job["capability_id"], "after_status": "cancelled", "reason_code": "operator_cancelled"},
    )
    conn.commit()
    return _job_payload(conn, job_id)


def expire_diagnostics(conn: sqlite3.Connection) -> dict:
    now = _now()
    rows = conn.execute(
        "select * from diagnostic_jobs where status in ('pending', 'queued', 'running') and expires_at < ?",
        (now,),
    ).fetchall()
    for row in rows:
        conn.execute("update diagnostic_jobs set status = 'expired', updated_at = ? where job_id = ?", (now, row["job_id"]))
        _update_story_diagnostic(conn, row["story_id"], "expired", "ttl_expired")
        _write_audit(conn, row["story_id"], "diagnostic_expired", {"job_id": row["job_id"], "reason_code": "ttl_expired"})
    conn.commit()
    return {"expired": len(rows)}


def record_diagnostic_result(conn: sqlite3.Connection, job_id: str, status: str, summary: str, projection: dict | None = None) -> dict:
    if status not in {"succeeded", "failed", "unavailable"}:
        raise ValueError("invalid_result_status")
    job = _job_row(conn, job_id)
    if job["status"] in TERMINAL_STATUSES:
        raise ValueError("job_already_terminal")
    result_summary = _normalize_result_summary(summary)
    now = _now()
    result_id = f"diagnostic-result-{job_id}"
    conn.execute(
        """
        insert into diagnostic_results (
          result_id, job_id, story_id, status, summary, projection_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (result_id, job_id, job["story_id"], status, result_summary, _dumps(projection or {}), now),
    )
    conn.execute("update diagnostic_jobs set status = ?, updated_at = ? where job_id = ?", (status, now, job_id))
    if status == "succeeded":
        _append_diagnostic_evidence(conn, job["story_id"], result_id, result_summary)
    _update_story_diagnostic(conn, job["story_id"], status, None if status == "succeeded" else status)
    _write_audit(
        conn,
        job["story_id"],
        "diagnostic_result_recorded",
        {"job_id": job_id, "result_id": result_id, "after_status": status, "reason_code": status},
    )
    conn.commit()
    return {"result_id": result_id, "job_id": job_id, "story_id": job["story_id"], "status": status, "summary": result_summary}


def _capability_state(conn: sqlite3.Connection, story_id: str, capability_id: str) -> dict:
    policy = conn.execute("select diagnostic_policy from effective_policies where id = 1").fetchone()
    manifest = MANIFEST[capability_id]
    if policy and policy["diagnostic_policy"] == "disabled":
        state, reason = "unavailable", "policy_denied"
    else:
        collector_id = _collector_id(conn, story_id)
        collector = (
            conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
            if collector_id
            else conn.execute("select * from collectors order by updated_at desc limit 1").fetchone()
        )
        if collector is None or collector["source_status"] == "offline":
            state, reason = "queueable", "collector_offline"
        elif collector["source_status"] in {"source_locked", "source_missing"}:
            state, reason = "unavailable", collector["source_status"]
        else:
            state, reason = "available", None
    return {"capability_id": capability_id, "label": manifest["label"], "state": state, "reason_code": reason}


def _collector_id(conn: sqlite3.Connection, story_id: str | None = None) -> str | None:
    if story_id:
        story = _story_row(conn, story_id)
        for evidence_ref in json.loads(story["evidence_refs_json"]):
            row = conn.execute(
                """
                select f.collector_id
                from evidence_projections p
                join observed_facts f on f.fact_id = p.fact_id
                where p.projection_id = ?
                limit 1
                """,
                (evidence_ref,),
            ).fetchone()
            if row:
                return row["collector_id"]
        for evidence_ref in json.loads(story["evidence_refs_json"]):
            row = conn.execute("select collector_id from observed_facts where fact_id = ?", (evidence_ref,)).fetchone()
            if row:
                return row["collector_id"]
    row = conn.execute("select collector_id from collectors order by updated_at desc limit 1").fetchone()
    return row["collector_id"] if row else None


def _command(conn: sqlite3.Connection, story_id: str, capability_id: str) -> dict:
    story = _story_row(conn, story_id)
    manifest = MANIFEST[capability_id]
    return {
        "command_id": manifest["command_id"],
        "template": manifest["template"],
        "args": {"story_id": story_id, "evidence_refs": json.loads(story["evidence_refs_json"])},
    }


def _append_diagnostic_evidence(conn: sqlite3.Connection, story_id: str, result_id: str, summary: str) -> None:
    story = _story_row(conn, story_id)
    snapshot = _loads(story["current_snapshot_json"])
    evidence_chain = list(snapshot.get("evidence_chain", []))
    evidence_chain.append({"evidence_ref": result_id, "category": "diagnostic_result", "summary": summary, "quality": "high"})
    snapshot["evidence_chain"] = evidence_chain
    evidence_refs = sorted(set(json.loads(story["evidence_refs_json"]) + [result_id]))
    snapshot_hash = hashlib.sha256(_dumps(snapshot).encode("utf-8")).hexdigest()
    conn.execute(
        """
        update observation_stories
        set evidence_refs_json = ?, current_snapshot_json = ?, snapshot_hash = ?, updated_at = ?
        where story_id = ?
        """,
        (_dumps(evidence_refs), _dumps(snapshot), snapshot_hash, _now(), story_id),
    )


def _update_story_diagnostic(conn: sqlite3.Connection, story_id: str, status: str, reason_code: str | None) -> None:
    conn.execute(
        "update observation_stories set diagnostic_status_summary_json = ?, updated_at = ? where story_id = ?",
        (_dumps({"status": status, "reason_code": reason_code}), _now(), story_id),
    )


def _active_job(conn: sqlite3.Connection, story_id: str) -> dict | None:
    row = conn.execute(
        "select * from diagnostic_jobs where story_id = ? and status in ('pending', 'queued', 'running') order by rowid desc limit 1",
        (story_id,),
    ).fetchone()
    return _job_public(row) if row else None


def _job_payload(conn: sqlite3.Connection, job_id: str) -> dict:
    return _job_public(_job_row(conn, job_id))


def _job_public(row: sqlite3.Row) -> dict:
    return {
        "job_id": row["job_id"],
        "story_id": row["story_id"],
        "collector_id": row["collector_id"],
        "capability_id": row["capability_id"],
        "status": row["status"],
        "reason_code": row["reason_code"],
        "command": _loads(row["command_json"]),
        "expires_at": row["expires_at"],
    }


def _story_row(conn: sqlite3.Connection, story_id: str) -> sqlite3.Row:
    row = conn.execute("select * from observation_stories where story_id = ?", (story_id,)).fetchone()
    if row is None:
        raise LookupError(story_id)
    return row


def _job_row(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute("select * from diagnostic_jobs where job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise LookupError(job_id)
    return row


def _normalize_result_summary(summary: str) -> str:
    value = " ".join((summary or "").split()).strip()
    if not value:
        raise ValueError("result_summary_required")
    return value[:4000]


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
