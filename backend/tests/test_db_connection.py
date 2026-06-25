from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.db.connection import connect


def test_concurrent_connections_initialize_schema_once_without_locking(tmp_path):
    db_path = tmp_path / "observer.sqlite"

    def read_collectors() -> int:
        with connect(db_path) as conn:
            return conn.execute("select count(*) from collectors").fetchone()[0]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: read_collectors(), range(24)))

    assert results == [0] * 24


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
