from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.db.connection import connect, write_lock


def test_concurrent_connections_initialize_schema_once_without_locking(tmp_path):
    db_path = tmp_path / "observer.sqlite"

    def read_collectors() -> int:
        with connect(db_path) as conn:
            return conn.execute("select count(*) from collectors").fetchone()[0]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: read_collectors(), range(24)))

    assert results == [0] * 24


def test_write_lock_serializes_concurrent_writers(tmp_path):
    """多线程并发 write_lock，验证串行化：同时只有一个线程在锁内。"""
    db_path = tmp_path / "observer.sqlite"
    counter_lock = threading.Lock()
    current_inside = 0
    peak_inside = 0

    def writer(idx: int) -> int:
        nonlocal current_inside, peak_inside
        with write_lock(db_path):
            with counter_lock:
                current_inside += 1
                peak_inside = max(peak_inside, current_inside)
            time.sleep(0.02)  # 持锁 20ms，扩大冲突窗口
            with counter_lock:
                current_inside -= 1
        return idx

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(writer, range(8)))

    assert sorted(results) == list(range(8))
    assert peak_inside == 1, f"串行化失败：同时有 {peak_inside} 个线程在锁内"


def test_write_lock_rolls_back_on_exception(tmp_path):
    """write_lock 内抛异常时自动 rollback，不留下未 commit 的脏数据。"""
    db_path = tmp_path / "observer.sqlite"

    with write_lock(db_path) as conn:
        conn.execute("create table t (id integer primary key, v text)")
        conn.commit()

    class _Boom(Exception):
        pass

    # write_lock 内写入但未 commit，然后抛异常 → rollback 应撤销
    try:
        with write_lock(db_path) as conn:
            conn.execute("insert into t (v) values ('should_be_rolled_back')")
            raise _Boom("simulated failure")
    except _Boom:
        pass

    with connect(db_path) as conn:
        rows = conn.execute("select v from t").fetchall()

    assert rows == [], "异常前未 commit 的写入应被 rollback 撤销"


def test_write_lock_reentrant(tmp_path):
    """同线程嵌套 write_lock 不死锁（RLock 可重入）。

    注意：嵌套 write_lock 会创建两个独立连接。外层须先 commit 释放 SQLite 写锁，
    内层才能写。RLock 只防止应用层死锁，当前代码库无嵌套写调用，RLock 纯为防御。
    """
    db_path = tmp_path / "observer.sqlite"

    with write_lock(db_path) as conn_outer:
        conn_outer.execute("create table t (id integer primary key, v text)")
        conn_outer.commit()  # 提交建表，释放 SQLite 写锁
        with write_lock(db_path) as conn_inner:
            conn_inner.execute("insert into t (v) values ('inner')")
            conn_inner.commit()
        conn_outer.execute("insert into t (v) values ('outer')")
        conn_outer.commit()

    with connect(db_path) as conn:
        rows = conn.execute("select v from t order by id").fetchall()

    assert [r["v"] for r in rows] == ["inner", "outer"]


def test_concurrent_writes_no_operational_error(tmp_path):
    """并发写不抛 OperationalError：write_lock 把 SQLite 锁竞争转为应用层排队。

    这是本次架构修复的核心成功标准——多线程并发写不再因 SQLite busy_timeout 超时
    抛 OperationalError，而是通过 _WRITE_LOCK 有序排队。
    """
    db_path = tmp_path / "observer.sqlite"
    errors: list[str] = []

    with write_lock(db_path) as conn:
        conn.execute("create table t (id integer primary key, v text)")
        conn.commit()

    def writer(idx: int) -> None:
        try:
            with write_lock(db_path) as conn:
                for i in range(10):
                    conn.execute("insert into t (v) values (?)", (f"writer-{idx}-row-{i}",))
                conn.commit()
        except sqlite3.OperationalError as exc:
            errors.append(f"writer-{idx}: {exc}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(writer, range(12)))

    assert errors == [], f"并发写出现 OperationalError: {errors}"

    with connect(db_path) as conn:
        count = conn.execute("select count(*) from t").fetchone()[0]
    assert count == 12 * 10, f"期望 120 行，实际 {count} 行"


def test_initialize_creates_current_collector_and_signal_schema(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        collector_columns = {row["name"] for row in conn.execute("pragma table_info(collectors)").fetchall()}
        signal_columns = {row["name"] for row in conn.execute("pragma table_info(behavior_signals)").fetchall()}
        policy_columns = {row["name"] for row in conn.execute("pragma table_info(effective_policies)").fetchall()}
        old_tables = {
            row["name"]
            for row in conn.execute(
                "select name from sqlite_master where type='table' and name in ('observation_stories', 'story_handling_states')"
            ).fetchall()
        }

    assert {"runtime_phase", "last_seen_at", "last_cycle_duration_ms", "last_error"} <= collector_columns
    assert {
        "signal_kind",
        "why_it_matters",
        "affected_scope_json",
        "evidence_groups_json",
        "linked_conversations_json",
        "first_seen_at",
        "last_seen_at",
        "last_event_at",
        "occurrence_count",
        "latest_fact_id",
        "latest_summary",
    } <= signal_columns
    assert {
        "collection_interval_seconds",
        "max_events_per_cycle",
        "upload_batch_size",
        "worker_poll_interval_seconds",
    } <= policy_columns
    assert "raw_upload_default" not in policy_columns
    assert old_tables == set()


def test_initialize_creates_current_query_indexes(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        fact_indexes = {row["name"] for row in conn.execute("pragma index_list(observed_facts)").fetchall()}
        signal_indexes = {row["name"] for row in conn.execute("pragma index_list(behavior_signals)").fetchall()}
        signature_indexes = {row["name"] for row in conn.execute("pragma index_list(error_signatures)").fetchall()}

    assert "idx_observed_facts_created_at" in fact_indexes
    assert "idx_observed_facts_conversation_occurred" in fact_indexes
    assert "idx_observed_facts_fact_type_created_at" in fact_indexes
    assert "idx_observed_facts_category_occurred_at" in fact_indexes
    assert "idx_behavior_signals_decision_last_event" in signal_indexes
    assert "idx_behavior_signals_kind_last_event" in signal_indexes
    assert "idx_error_signatures_category_key" in signature_indexes
