from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.behavior_signals.service import update_signal_scope

JOB_STATUS = ("pending", "running", "succeeded", "failed")
JOB_TYPE_SIGNAL_UPDATE = "behavior_signal_update"
JOB_TYPE_SIGNAL_REBUILD = "behavior_signal_rebuild"
JOB_TYPE_PERF_ROLLUP_UPDATE = "perf_rollup_update"
JOB_TYPE_PERF_ROLLUP_REBUILD = "perf_rollup_rebuild"
RUNNING_LEASE_SECONDS = 300
# OperationalError (database is locked) 是临时性锁竞争，给更高的重试上限。
# 永久性错误（ValueError 等）3 次后放弃。
TRANSIENT_ERROR_MAX_ATTEMPTS = 100
PERMANENT_ERROR_MAX_ATTEMPTS = 3
# last_error 截断长度，避免异常消息过长撑爆 DB 行。
LAST_ERROR_MAX_LENGTH = 500


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _is_transient_db_error(exc: Exception) -> bool:
    """判断是否为临时性数据库锁竞争错误（m1：缩小 OperationalError 范围）。

    只有 "locked"/"busy" 类 OperationalError 才算临时性，给高重试上限；
    其他 OperationalError（如 "no such table"）按永久性错误处理。
    """
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def _format_error(exc: Exception) -> str:
    """格式化 last_error：包含类型名和消息（m5），截断到 LAST_ERROR_MAX_LENGTH。"""
    text = f"{type(exc).__name__}: {exc}"
    if len(text) > LAST_ERROR_MAX_LENGTH:
        # 截断时加省略号，便于区分"正好 500 字符"和"被截断"（m-3）。
        text = text[:LAST_ERROR_MAX_LENGTH] + "..."
    return text


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
        result = _dispatch_job(conn, job, reason)
    except Exception as exc:
        # M1：回滚 _dispatch_job 的部分写入，避免被 _mark_failed 的 commit 一起提交。
        # _dispatch_job 的所有子路径（update_signal_scope、build_perf_rollups）只在最后 commit，
        # 中途抛异常会留下未提交的部分写入；若不回滚，_mark_failed 的 conn.commit() 会把这些
        # 脏数据一起落库。特别地，build_perf_rollups 先 delete 再循环 insert，若 insert 阶段抛
        # 异常且未回滚，会丢失该 window 的全部历史 rollup 数据。
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
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


def _dispatch_job(conn: sqlite3.Connection, job: sqlite3.Row, reason: str) -> dict:
    """按 job_type 分发到对应处理器（审查 I3 修正）。"""
    if job["job_type"] in (JOB_TYPE_PERF_ROLLUP_UPDATE, JOB_TYPE_PERF_ROLLUP_REBUILD):
        from app.perf.service import build_perf_rollups
        return build_perf_rollups(conn, window=job["scope_id"])
    return update_signal_scope(
        conn,
        job_type=job["job_type"],
        scope_type=job["scope_type"],
        scope_id=job["scope_id"],
        reason=reason,
    )


def _claim_next_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    try:
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
    except sqlite3.OperationalError:
        # database is locked：其他连接正持有写锁，跳过本次 claim，下个 cycle 重试。
        # M2：claim UPDATE 也纳入同一 try/except，避免 claim 阶段锁竞争崩溃 worker cycle。
        # 回滚未提交的部分写入（如 _recover_stale_running_jobs 的 UPDATE），保持连接干净。
        # 回归：07/15-07/17 多次 worker cycle failed 根因。
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        return None


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
    # OperationalError (database is locked) 是临时性锁竞争，不是 job 本身的问题。
    # 给更高的重试上限，避免因短暂锁竞争永久标 failed。
    # 回归：ref:948e68c21fb5e4fa 在 attempts=32 时遇锁竞争被永久标 failed，
    # 但同类 job ref:ea976ff49a529928 attempts=49 仍能成功。
    # m1：只把 locked/busy 类 OperationalError 当临时性，其他按永久性处理。
    is_transient = _is_transient_db_error(exc)
    max_attempts = TRANSIENT_ERROR_MAX_ATTEMPTS if is_transient else PERMANENT_ERROR_MAX_ATTEMPTS
    status = "failed" if attempts >= max_attempts else "pending"
    now = now_iso()
    error = _format_error(exc)
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
