from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta


MANIFEST = {
    "codex_tool_failure_context": {
        "label": "工具失败上下文补证",
        "command_id": "collect_codex_tool_failure_context",
        "template": "tool_failure_context.v1",
        "output_schema": "tool_failure_context.v1",
        "signal_kinds": {"tool_execution_failure", "tool_execution_timeout", "workflow_step_failure", "workflow_step_timeout"},
    }
}
TERMINAL_STATUSES = {"succeeded", "failed", "expired", "unavailable", "cancelled"}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _loads(value: str) -> dict:
    return json.loads(value or "{}")


def get_enrichment_availability(conn: sqlite3.Connection, signal_id: str) -> dict:
    _signal_row(conn, signal_id)
    expire_enrichments(conn)
    active_job = _active_job(conn, signal_id)
    return {
        "signal_id": signal_id,
        "active_job": active_job,
        "capabilities": [_capability_state(conn, signal_id, capability_id) for capability_id in MANIFEST],
    }


def request_enrichment(conn: sqlite3.Connection, signal_id: str, capability_id: str) -> dict:
    if capability_id not in MANIFEST:
        raise ValueError("missing_capability")
    _signal_row(conn, signal_id)
    expire_enrichments(conn)
    if active_job := _active_job(conn, signal_id):
        if active_job["capability_id"] == capability_id:
            return _job_payload(conn, active_job["job_id"])
        raise ValueError("active_enrichment_exists")
    capability = _capability_state(conn, signal_id, capability_id)
    if capability["state"] == "unavailable":
        raise ValueError(capability["reason_code"] or "enrichment_unavailable")
    status = "queued" if capability["state"] == "queueable" else "pending"
    now = _now()
    expires_at = (datetime.now(UTC) + timedelta(minutes=15)).replace(microsecond=0).isoformat()
    command = _command(conn, signal_id, capability_id)
    collector_id = _collector_id(conn, signal_id)
    job_count = conn.execute("select count(*) from enrichment_jobs where signal_id = ?", (signal_id,)).fetchone()[0]
    job_id = hashlib.sha256(f"{signal_id}:{capability_id}:{now}:{job_count}".encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        insert into enrichment_jobs (
          job_id, signal_id, collector_id, capability_id, status, command_json, reason_code,
          requested_by, requested_at, expires_at, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, 'fixed-management-account', ?, ?, ?)
        """,
        (
            job_id,
            signal_id,
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
    _update_signal_enrichment(conn, signal_id, status, capability["reason_code"])
    _write_audit(
        conn,
        signal_id,
        "enrichment_requested",
        {"capability_id": capability_id, "job_id": job_id, "after_status": status, "reason_code": capability["reason_code"]},
    )
    conn.commit()
    return _job_payload(conn, job_id)


def get_next_collector_enrichment(conn: sqlite3.Connection, collector_id: str) -> dict:
    collector = conn.execute("select * from collectors where collector_id = ?", (collector_id,)).fetchone()
    if collector is None:
        raise LookupError(collector_id)
    expire_enrichments(conn)
    now = _now()
    row = conn.execute(
        """
        select * from enrichment_jobs
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
        "update enrichment_jobs set status = 'running', collector_id = ?, updated_at = ? where job_id = ?",
        (collector_id, now, row["job_id"]),
    )
    _update_signal_enrichment(conn, row["signal_id"], "running", None)
    _write_audit(conn, row["signal_id"], "enrichment_started", {"job_id": row["job_id"], "collector_id": collector_id})
    conn.commit()
    return _job_payload(conn, row["job_id"])


def record_collector_enrichment_result(conn: sqlite3.Connection, collector_id: str, job_id: str, payload: dict) -> dict:
    job = _job_row(conn, job_id)
    if job["collector_id"] and job["collector_id"] != collector_id:
        raise ValueError("collector_mismatch")
    return record_enrichment_result(
        conn,
        job_id,
        payload.get("status", ""),
        payload.get("summary", ""),
        payload.get("projection"),
        payload.get("redaction"),
    )


def cancel_enrichment(conn: sqlite3.Connection, job_id: str) -> dict:
    job = _job_row(conn, job_id)
    if job["status"] not in {"pending", "queued"}:
        raise ValueError("cannot_cancel")
    now = _now()
    conn.execute("update enrichment_jobs set status = 'cancelled', updated_at = ? where job_id = ?", (now, job_id))
    _update_signal_enrichment(conn, job["signal_id"], "cancelled", "operator_cancelled")
    _write_audit(
        conn,
        job["signal_id"],
        "enrichment_cancelled",
        {"job_id": job_id, "capability_id": job["capability_id"], "after_status": "cancelled", "reason_code": "operator_cancelled"},
    )
    conn.commit()
    return _job_payload(conn, job_id)


def expire_enrichments(conn: sqlite3.Connection) -> dict:
    now = _now()
    rows = conn.execute(
        "select * from enrichment_jobs where status in ('pending', 'queued', 'running') and expires_at < ?",
        (now,),
    ).fetchall()
    for row in rows:
        conn.execute("update enrichment_jobs set status = 'expired', updated_at = ? where job_id = ?", (now, row["job_id"]))
        _update_signal_enrichment(conn, row["signal_id"], "expired", "ttl_expired")
        _write_audit(conn, row["signal_id"], "enrichment_expired", {"job_id": row["job_id"], "reason_code": "ttl_expired"})
    conn.commit()
    return {"expired": len(rows)}


def record_enrichment_result(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    summary: str,
    projection: dict | None = None,
    redaction: dict | None = None,
) -> dict:
    if status not in {"succeeded", "failed", "unavailable"}:
        raise ValueError("invalid_result_status")
    job = _job_row(conn, job_id)
    if job["status"] in TERMINAL_STATUSES:
        raise ValueError("job_already_terminal")
    result_summary = _normalize_result_summary(summary)
    now = _now()
    result_id = f"enrichment-result-{job_id}"
    output_schema = str((projection or {}).get("output_schema") or MANIFEST[job["capability_id"]]["output_schema"])
    conn.execute(
        """
        insert into enrichment_results (
          result_id, job_id, signal_id, capability_id, output_schema, status, summary,
          projection_json, redaction_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result_id,
            job_id,
            job["signal_id"],
            job["capability_id"],
            output_schema,
            status,
            result_summary,
            _dumps(projection or {}),
            _dumps(redaction or (projection or {}).get("redaction") or {}),
            now,
        ),
    )
    conn.execute("update enrichment_jobs set status = ?, updated_at = ? where job_id = ?", (status, now, job_id))
    if status == "succeeded":
        _append_enrichment_evidence(conn, job["signal_id"], result_id, result_summary)
    _update_signal_enrichment(conn, job["signal_id"], status, None if status == "succeeded" else status)
    _write_audit(
        conn,
        job["signal_id"],
        "enrichment_result_recorded",
        {"job_id": job_id, "result_id": result_id, "after_status": status, "reason_code": status},
    )
    conn.commit()
    return {"result_id": result_id, "job_id": job_id, "signal_id": job["signal_id"], "status": status, "summary": result_summary}


def _capability_state(conn: sqlite3.Connection, signal_id: str, capability_id: str) -> dict:
    policy = conn.execute("select enrichment_mode from effective_policies where id = 1").fetchone()
    manifest = MANIFEST[capability_id]
    signal = _signal_row(conn, signal_id)
    if signal["signal_kind"] not in manifest["signal_kinds"]:
        state, reason = "unavailable", "capability_not_applicable"
    elif policy and policy["enrichment_mode"] == "disabled":
        state, reason = "unavailable", "policy_denied"
    else:
        collector_id = _collector_id(conn, signal_id)
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


def _collector_id(conn: sqlite3.Connection, signal_id: str | None = None) -> str | None:
    if signal_id:
        for evidence_ref in _signal_evidence_refs(conn, signal_id):
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
            row = conn.execute("select collector_id from observed_facts where fact_id = ?", (evidence_ref,)).fetchone()
            if row:
                return row["collector_id"]
    row = conn.execute("select collector_id from collectors order by updated_at desc limit 1").fetchone()
    return row["collector_id"] if row else None


def _command(conn: sqlite3.Connection, signal_id: str, capability_id: str) -> dict:
    _signal_row(conn, signal_id)
    manifest = MANIFEST[capability_id]
    return {
        "command_id": manifest["command_id"],
        "signal_id": signal_id,
        "capability_id": capability_id,
        "evidence_refs": _command_evidence_refs(conn, _signal_evidence_refs(conn, signal_id)),
    }


def _command_evidence_refs(conn: sqlite3.Connection, evidence_refs: list[str]) -> list[dict]:
    resolved = []
    for evidence_ref in evidence_refs:
        projection = conn.execute(
            """
            select p.projection_id, p.category, p.projection_json,
                   f.fact_id, f.source_event_id, f.source_refs_json, f.conversation_ref,
                   f.source_path_hash, f.source_event_type, f.occurred_at
            from evidence_projections p
            join observed_facts f on f.fact_id = p.fact_id
            where p.projection_id = ?
            limit 1
            """,
            (evidence_ref,),
        ).fetchone()
        if projection:
            resolved.append(_command_evidence_ref(projection["projection_id"], projection))
            continue
        fact = conn.execute(
            """
            select fact_id, category, source_event_id, source_refs_json, conversation_ref,
                   source_path_hash, source_event_type, occurred_at, '{}' as projection_json
            from observed_facts
            where fact_id = ?
            limit 1
            """,
            (evidence_ref,),
        ).fetchone()
        if fact:
            resolved.append(_command_evidence_ref(fact["fact_id"], fact))
    return resolved


def _command_evidence_ref(evidence_ref: str, row: sqlite3.Row) -> dict:
    source_refs = _loads(row["source_refs_json"])
    return {
        "evidence_ref": evidence_ref,
        "fact_id": row["fact_id"],
        "category": row["category"],
        "source_event_id": row["source_event_id"],
        "source_path_hash": row["source_path_hash"],
        "source_line": source_refs.get("line"),
        "conversation_ref": row["conversation_ref"] or source_refs.get("conversation_ref"),
        "source_event_type": row["source_event_type"],
        "occurred_at": row["occurred_at"],
    }


def _append_enrichment_evidence(conn: sqlite3.Connection, signal_id: str, result_id: str, summary: str) -> None:
    signal = _signal_row(conn, signal_id)
    groups = json.loads(signal["evidence_groups_json"] or "[]")
    enrichment_item = {"evidence_ref": result_id, "category": "enrichment_result", "summary": summary, "quality": "high"}
    target = next((group for group in groups if group.get("title") == "工具失败上下文补证"), None)
    if target is None:
        target = {"group_id": "failure:enrichment", "group_type": "failure", "title": "工具失败上下文补证", "summary": "补证结果", "count": 0, "items": []}
        groups.append(target)
    target["items"] = [*target.get("items", []), enrichment_item]
    target["count"] = len(target["items"])
    snapshot_hash = hashlib.sha256(_dumps(groups).encode("utf-8")).hexdigest()
    conn.execute(
        """
        update behavior_signals
        set evidence_groups_json = ?, snapshot_hash = ?, updated_at = ?
        where signal_id = ?
        """,
        (_dumps(groups), snapshot_hash, _now(), signal_id),
    )


def _update_signal_enrichment(conn: sqlite3.Connection, signal_id: str, status: str, reason_code: str | None) -> None:
    conn.execute(
        "update behavior_signals set enrichment_status_summary_json = ?, updated_at = ? where signal_id = ?",
        (_dumps({"status": status, "reason_code": reason_code}), _now(), signal_id),
    )


def _active_job(conn: sqlite3.Connection, signal_id: str) -> dict | None:
    row = conn.execute(
        "select * from enrichment_jobs where signal_id = ? and status in ('pending', 'queued', 'running') order by rowid desc limit 1",
        (signal_id,),
    ).fetchone()
    return _job_public(row) if row else None


def _job_payload(conn: sqlite3.Connection, job_id: str) -> dict:
    return _job_public(_job_row(conn, job_id))


def _job_public(row: sqlite3.Row) -> dict:
    return {
        "job_id": row["job_id"],
        "signal_id": row["signal_id"],
        "collector_id": row["collector_id"],
        "capability_id": row["capability_id"],
        "status": row["status"],
        "reason_code": row["reason_code"],
        "command": _loads(row["command_json"]),
        "expires_at": row["expires_at"],
    }


def _signal_row(conn: sqlite3.Connection, signal_id: str) -> sqlite3.Row:
    row = conn.execute("select * from behavior_signals where signal_id = ?", (signal_id,)).fetchone()
    if row is None:
        raise LookupError(signal_id)
    return row


def _signal_evidence_refs(conn: sqlite3.Connection, signal_id: str) -> list[str]:
    signal = _signal_row(conn, signal_id)
    refs: list[str] = []
    for group in json.loads(signal["evidence_groups_json"] or "[]"):
        for item in group.get("items", []):
            evidence_ref = item.get("evidence_ref") or item.get("fact_id")
            if evidence_ref:
                refs.append(str(evidence_ref))
    return sorted(set(refs))


def _job_row(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute("select * from enrichment_jobs where job_id = ?", (job_id,)).fetchone()
    if row is None:
        raise LookupError(job_id)
    return row


def _normalize_result_summary(summary: str) -> str:
    value = " ".join((summary or "").split()).strip()
    if not value:
        raise ValueError("result_summary_required")
    return value[:4000]


def _write_audit(conn: sqlite3.Connection, signal_id: str, action: str, metadata: dict) -> None:
    now = _now()
    audit_id = hashlib.sha256(f"{signal_id}:{action}:{now}:{_dumps(metadata)}".encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        insert into audit_logs (audit_id, object_type, object_id, action, actor, metadata_json, created_at)
        values (?, 'behavior_signal', ?, ?, 'fixed-management-account', ?, ?)
        """,
        (audit_id, signal_id, action, _dumps(metadata), now),
    )
