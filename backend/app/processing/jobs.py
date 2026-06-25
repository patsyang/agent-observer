from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.behavior_signals.service import update_signal_scope

JOB_STATUS = ("pending", "running", "succeeded", "failed")
JOB_TYPE_SIGNAL_UPDATE = "behavior_signal_update"
JOB_TYPE_SIGNAL_REBUILD = "behavior_signal_rebuild"
RUNNING_LEASE_SECONDS = 300


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def enqueue_processing_job(
    conn: sqlite3.Connection,
    *,
    job_type: str,
    scope_type: str,
    scope_id: str,
    priority: int = 50,
) -> dict:
    job_id = f"{job_type}:{scope_type}:{scope_id}"
    now = now_iso()
    row = conn.execute("select status from processing_jobs where job_id = ?", (job_id,)).fetchone()
    if row is None:
        conn.execute(
            """
            insert into processing_jobs (
              job_id, job_type, scope_type, scope_id, status, priority, attempts,
              last_error, created_at, updated_at, started_at, finished_at
            ) values (?, ?, ?, ?, 'pending', ?, 0, '', ?, ?, null, null)
            """,
            (job_id, job_type, scope_type, scope_id, int(priority), now, now),
        )
    elif row["status"] in {"pending", "running"}:
        conn.execute(
            "update processing_jobs set priority = max(priority, ?), updated_at = ? where job_id = ?",
            (int(priority), now, job_id),
        )
    else:
        conn.execute(
            """
            update processing_jobs
            set status = 'pending', priority = ?, last_error = '', updated_at = ?,
                started_at = null, finished_at = null
            where job_id = ?
            """,
            (int(priority), now, job_id),
        )
    return {"job_id": job_id, "job_type": job_type, "scope_type": scope_type, "scope_id": scope_id}


def enqueue_global_signal_rebuild(conn: sqlite3.Connection, reason: str = "api") -> dict:
    job = enqueue_processing_job(
        conn,
        job_type=JOB_TYPE_SIGNAL_REBUILD,
        scope_type="global",
        scope_id="all",
        priority=100,
    )
    conn.commit()
    return {"status": "queued", "reason": reason, **job}


def processing_status(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "select status, count(*) as count from processing_jobs group by status"
    ).fetchall()
    counts = {status: 0 for status in JOB_STATUS}
    for row in rows:
        counts[str(row["status"])] = int(row["count"])
    latest_failed = conn.execute(
        """
        select job_id, last_error, updated_at
        from processing_jobs
        where status = 'failed'
        order by updated_at desc
        limit 1
        """
    ).fetchone()
    state = "failed" if counts["failed"] else "running" if counts["running"] else "pending" if counts["pending"] else "idle"
    return {
        "state": state,
        "counts": counts,
        "latest_failed": dict(latest_failed) if latest_failed else None,
    }


def run_next_job(conn: sqlite3.Connection, reason: str = "worker") -> dict:
    job = _claim_next_job(conn)
    if job is None:
        return {"status": "idle", "processed": 0}
    try:
        result = update_signal_scope(
            conn,
            job_type=job["job_type"],
            scope_type=job["scope_type"],
            scope_id=job["scope_id"],
            reason=reason,
        )
    except Exception as exc:
        return _mark_failed(conn, job, exc)
    now = now_iso()
    conn.execute(
        """
        update processing_jobs
        set status = 'succeeded', last_error = '', updated_at = ?, finished_at = ?
        where job_id = ?
        """,
        (now, now, job["job_id"]),
    )
    conn.commit()
    return {"status": "processed", "processed": 1, "job_id": job["job_id"], "result": result}


def _claim_next_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    _recover_stale_running_jobs(conn)
    now = now_iso()
    row = conn.execute(
        """
        update processing_jobs
        set status = 'running', attempts = attempts + 1, updated_at = ?, started_at = ?
        where job_id = (
          select job_id
          from processing_jobs
          where status = 'pending'
          order by priority desc, updated_at, job_id
          limit 1
        )
        returning *
        """,
        (now, now),
    ).fetchone()
    conn.commit()
    return row


def _recover_stale_running_jobs(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(UTC) - timedelta(seconds=RUNNING_LEASE_SECONDS)).replace(microsecond=0).isoformat()
    conn.execute(
        """
        update processing_jobs
        set status = 'pending', updated_at = ?, last_error = 'running_lease_expired'
        where status = 'running' and coalesce(started_at, updated_at) < ?
        """,
        (now_iso(), cutoff),
    )


def _mark_failed(conn: sqlite3.Connection, job: sqlite3.Row, exc: Exception) -> dict:
    attempts = int(job["attempts"])
    status = "failed" if attempts >= 3 else "pending"
    now = now_iso()
    error = type(exc).__name__
    conn.execute(
        """
        update processing_jobs
        set status = ?, last_error = ?, updated_at = ?, finished_at = ?
        where job_id = ?
        """,
        (status, error, now, now, job["job_id"]),
    )
    conn.commit()
    return {"status": status, "processed": 0, "job_id": job["job_id"], "error": error}
