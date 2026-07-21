from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.processing import jobs as jobs_mod
from app.processing.jobs import (
    _claim_next_job,
    _mark_failed,
    enqueue_global_signal_rebuild,
    enqueue_processing_job,
    processing_status,
    run_next_job,
)
from source_payloads import default_versions


def _failure_batch() -> dict:
    return {
        "batch_id": "batch-processing",
        **default_versions(),
        "collector_id": "collector-codex",
        "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
        "cursor": "cursor",
        "items": [
            {
                "source_event_id": "tool-failure-processing",
                "fact_type": "error",
                "category": "tool_execution_failure",
                "quality": "high",
                "severity": "high",
                "summary": "function_call_output failed with exit_code=1",
                "occurred_at": "2026-06-18T10:00:00+00:00",
                "span": "event:tool-failure-processing",
                "raw_hash": "hash-tool-failure-processing",
                "projection": {"tool_name": "exec_command", "exit_code": 1},
                "error_signature": {
                    "signature_key": "tool_execution_failure:exec_command:processing:1",
                    "category": "tool_execution_failure",
                },
                "source_refs": {"conversation_ref": "conversation-processing"},
                "source_specific": {"event_type": "tool_result"},
            }
        ],
    }


def test_processing_job_updates_signal_and_status(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest = ingest_telemetry(conn, _failure_batch())
        before = processing_status(conn)
        result = run_next_job(conn, reason="test")
        after = processing_status(conn)
        signal_count = conn.execute("select count(*) from behavior_signals").fetchone()[0]

    assert ingest["processing_jobs_queued"] == 1
    assert before["state"] == "pending"
    assert result["status"] == "processed"
    assert after["state"] == "idle"
    assert after["counts"]["succeeded"] == 1
    assert signal_count == 1


def test_processing_job_merge_and_retry_failure(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        first = enqueue_processing_job(conn, job_type="behavior_signal_update", scope_type="unsupported", scope_id="bad")
        second = enqueue_processing_job(conn, job_type="behavior_signal_update", scope_type="unsupported", scope_id="bad")
        conn.commit()
        for _ in range(3):
            result = run_next_job(conn, reason="test")
        row = conn.execute("select status, attempts, last_error from processing_jobs where job_id = ?", (first["job_id"],)).fetchone()

    assert first == second
    assert result["status"] == "failed"
    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert row["last_error"] == "ValueError: unsupported_processing_scope"


def test_stale_running_job_is_recovered_and_processed(tmp_path):
    stale_started_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _failure_batch())
        conn.execute(
            """
            update processing_jobs
            set status = 'running', started_at = ?, updated_at = ?
            """,
            (stale_started_at, stale_started_at),
        )
        conn.commit()
        result = run_next_job(conn, reason="test")
        row = conn.execute("select status, attempts from processing_jobs").fetchone()

    assert result["status"] == "processed"
    assert row["status"] == "succeeded"
    assert row["attempts"] == 1


def test_global_rebuild_is_queued_not_executed_synchronously(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        queued = enqueue_global_signal_rebuild(conn, reason="api")
        status = processing_status(conn)
        signal_count = conn.execute("select count(*) from behavior_signals").fetchone()[0]

    assert queued["job_id"] == "behavior_signal_rebuild:global:all"
    assert queued["status"] == "queued"
    assert status["state"] == "pending"
    assert signal_count == 0


# ---------- OperationalError 不应永久标 failed（database is locked 回归） ----------

def _set_attempts(conn, job_id: str, attempts: int) -> sqlite3.Row:
    """设置 processing_jobs.attempts 并返回 row，供 _mark_failed 使用。"""
    conn.execute("update processing_jobs set attempts = ? where job_id = ?", (attempts, job_id))
    conn.commit()
    return conn.execute("select * from processing_jobs where job_id = ?", (job_id,)).fetchone()


def test_mark_failed_operational_error_stays_pending_at_3(tmp_path):
    """OperationalError (database is locked) 是临时性锁竞争，attempts=3 不应标 failed。

    回归：ref:948e68c21fb5e4fa 在 attempts=32 时遇 OperationalError 被永久标 failed，
    但其他同类 job（ref:ea976ff49a529928）attempts=49 仍能成功。临时性错误不应因
    重试 3 次就放弃，应给更高的重试上限。
    """
    with connect(tmp_path / "observer.sqlite") as conn:
        job = enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()
        row = _set_attempts(conn, job["job_id"], 3)
        result = _mark_failed(conn, row, sqlite3.OperationalError("database is locked"))
        status = conn.execute(
            "select status from processing_jobs where job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
    assert result["status"] == "pending", "OperationalError 应标 pending 允许重试"
    assert status == "pending"


def test_mark_failed_value_error_fails_at_3(tmp_path):
    """ValueError 是永久性错误，attempts=3 时标 failed（行为不变）。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        job = enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()
        row = _set_attempts(conn, job["job_id"], 3)
        result = _mark_failed(conn, row, ValueError("unsupported_processing_scope"))
        status = conn.execute(
            "select status from processing_jobs where job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
    assert result["status"] == "failed"
    assert status == "failed"


def test_mark_failed_operational_error_fails_at_100(tmp_path):
    """OperationalError 重试 100 次仍失败才标 failed（防止无限重试）。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        job = enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()
        row = _set_attempts(conn, job["job_id"], 100)
        result = _mark_failed(conn, row, sqlite3.OperationalError("database is locked"))
        status = conn.execute(
            "select status from processing_jobs where job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
    assert result["status"] == "failed", "超过 100 次重试应放弃"
    assert status == "failed"


# ---------- m1：非锁类 OperationalError 按永久性错误处理 ----------

def test_mark_failed_non_lock_operational_error_fails_at_3(tmp_path):
    """m1：非锁类 OperationalError（如 'no such table'）按永久性错误处理，3 次后标 failed。

    缩小 OperationalError 分类：只有 "locked"/"busy" 类才算临时性锁竞争，
    其他 OperationalError（schema 错误、约束错误等）是永久性问题。
    """
    with connect(tmp_path / "observer.sqlite") as conn:
        job = enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()
        row = _set_attempts(conn, job["job_id"], 3)
        result = _mark_failed(conn, row, sqlite3.OperationalError("no such table: foo"))
        status = conn.execute(
            "select status from processing_jobs where job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
    assert result["status"] == "failed", "非锁类 OperationalError 应按永久性错误处理"
    assert status == "failed"


# ---------- M1：run_next_job 回滚 _dispatch_job 的部分写入 ----------

def test_run_next_job_rolls_back_partial_dispatch_writes(tmp_path, monkeypatch):
    """M1：_dispatch_job 抛异常时，run_next_job 应回滚部分写入。

    _dispatch_job 内部（update_signal_scope）只在最后 commit，中途抛异常会留下未提交的
    部分写入。若 run_next_job 不先 rollback，_mark_failed 的 conn.commit() 会把这些
    脏数据一起落库。本测试用探针表验证部分写入被回滚。
    """
    with connect(tmp_path / "observer.sqlite") as conn:
        # 预先创建探针表并提交（在 run_next_job 之前）
        conn.execute("create table _m1_probe(value text)")
        conn.commit()

        enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()

        # 模拟 _dispatch_job 部分写入后抛异常
        def failing_dispatch(conn_arg, job, reason):
            conn_arg.execute("insert into _m1_probe(value) values ('partial-write')")
            raise RuntimeError("dispatch failed mid-way")

        monkeypatch.setattr(jobs_mod, "_dispatch_job", failing_dispatch)

        result = run_next_job(conn, reason="test")
        probe_count = conn.execute("select count(*) from _m1_probe").fetchone()[0]
        job_status = conn.execute("select status from processing_jobs").fetchone()["status"]

    assert probe_count == 0, "部分写入应被回滚，不应被 _mark_failed 的 commit 提交"
    # RuntimeError 非临时性，attempts=1 < 3，应标 pending 允许重试
    assert result["status"] == "pending"
    assert job_status == "pending"


# ---------- M2：_claim_next_job 的 claim UPDATE 遇锁返回 None ----------

class _LockedClaimConn:
    """包装 connection，让 claim UPDATE（set status='running'）抛 OperationalError。

    sqlite3.Connection 是 C 扩展类型，不支持 monkeypatch.setattr 实例属性，
    因此用代理类拦截 execute。_recover_stale_running_jobs 的 UPDATE（set
    status='pending'）正常通过，只有 claim UPDATE 抛锁错误。
    """

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, *args, **kwargs):
        if "set status = 'running'" in sql.strip().lower():
            raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, *args, **kwargs)


def test_claim_next_job_returns_none_on_claim_update_locked(tmp_path):
    """M2：claim UPDATE 遇 OperationalError 时返回 None，不崩溃 worker cycle。

    _recover_stale_running_jobs 正常通过，但 claim UPDATE（set status='running'）
    抛 database is locked。_claim_next_job 应捕获并返回 None，job 保持 pending。
    """
    with connect(tmp_path / "observer.sqlite") as conn:
        enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()

        wrapped = _LockedClaimConn(conn)
        result = _claim_next_job(wrapped)
        job_status = conn.execute("select status from processing_jobs").fetchone()["status"]

    assert result is None, "claim UPDATE 遇锁应返回 None，不崩溃 worker cycle"
    assert job_status == "pending", "job 应保持 pending，未被 claim"


def test_claim_next_job_rolls_back_recover_on_claim_locked(tmp_path):
    """m-5：claim UPDATE 遇锁时，_recover_stale_running_jobs 的 UPDATE 也应被回滚。

    场景：有一个 stale running job（started_at 早于 lease cutoff）和一个 pending job。
    _recover_stale_running_jobs 先把 stale job 重置为 pending（未提交），然后 claim UPDATE
    遇锁抛异常。except 中的 rollback 应撤销 recover，stale job 回到 'running'，
    pending job 保持 'pending'。下个 cycle 会重新 recover，幂等无数据丢失。
    """
    stale_started_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        # stale running job（会被 _recover_stale_running_jobs 重置）
        conn.execute(
            """
            insert into processing_jobs (
              job_id, job_type, scope_type, scope_id, status, priority, attempts,
              last_error, created_at, updated_at, started_at, finished_at
            ) values (?, ?, ?, ?, 'running', 50, 1, '', ?, ?, ?, null)
            """,
            ("behavior_signal_update:risk:stale", "behavior_signal_update", "risk", "stale",
             stale_started_at, stale_started_at, stale_started_at),
        )
        # pending job（claim 的候选）
        enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()

        wrapped = _LockedClaimConn(conn)
        result = _claim_next_job(wrapped)
        statuses = {
            row["job_id"]: row["status"]
            for row in conn.execute("select job_id, status from processing_jobs")
        }

    assert result is None, "claim UPDATE 遇锁应返回 None"
    # recover 被回滚：stale job 回到 'running'，不会被误标 pending
    assert statuses["behavior_signal_update:risk:stale"] == "running", \
        "recover 的 UPDATE 应被回滚，stale job 应回到 'running' 等下个 cycle 重新 recover"
    # pending job 未被 claim
    assert statuses["behavior_signal_update:risk:test"] == "pending", \
        "pending job 应保持 pending，未被 claim"


# ---------- m-7：SQLITE_LOCKED（database table is locked）也判为临时性 ----------

def test_mark_failed_table_locked_stays_pending_at_3(tmp_path):
    """m-7：'database table is locked'（SQLITE_LOCKED）也应判为临时性锁竞争。

    m1 的 _is_transient_db_error 用 'locked' 关键字匹配，'database table is locked'
    含 'locked'，应被判临时性。补此测试锁定 SQLITE_LOCKED 覆盖。
    """
    with connect(tmp_path / "observer.sqlite") as conn:
        job = enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()
        row = _set_attempts(conn, job["job_id"], 3)
        result = _mark_failed(conn, row, sqlite3.OperationalError("database table is locked"))
        status = conn.execute(
            "select status from processing_jobs where job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
    assert result["status"] == "pending", "'database table is locked' 应判临时性"
    assert status == "pending"


# ---------- m-8：attempts 边界值（< max_attempts 应标 pending） ----------

def test_mark_failed_permanent_error_stays_pending_below_max(tmp_path):
    """m-8：永久性错误 attempts=2（< 3）应标 pending 允许重试，只有 >=3 才 failed。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        job = enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()
        row = _set_attempts(conn, job["job_id"], 2)
        result = _mark_failed(conn, row, ValueError("unsupported_processing_scope"))
        status = conn.execute(
            "select status from processing_jobs where job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
    assert result["status"] == "pending", "attempts=2 < 3 应标 pending"
    assert status == "pending"


def test_mark_failed_transient_error_stays_pending_below_max(tmp_path):
    """m-8：临时性错误 attempts=99（< 100）应标 pending 允许重试，只有 >=100 才 failed。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        job = enqueue_processing_job(
            conn, job_type="behavior_signal_update", scope_type="risk", scope_id="test"
        )
        conn.commit()
        row = _set_attempts(conn, job["job_id"], 99)
        result = _mark_failed(conn, row, sqlite3.OperationalError("database is locked"))
        status = conn.execute(
            "select status from processing_jobs where job_id = ?", (job["job_id"],)
        ).fetchone()["status"]
    assert result["status"] == "pending", "attempts=99 < 100 应标 pending"
    assert status == "pending"
