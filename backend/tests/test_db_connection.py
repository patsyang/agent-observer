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


def test_initialize_creates_current_collector_and_story_schema(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        collector_columns = {row["name"] for row in conn.execute("pragma table_info(collectors)").fetchall()}
        story_columns = {row["name"] for row in conn.execute("pragma table_info(observation_stories)").fetchall()}
        policy_columns = {row["name"] for row in conn.execute("pragma table_info(effective_policies)").fetchall()}

    assert {"runtime_phase", "last_seen_at", "last_cycle_duration_ms", "last_error"} <= collector_columns
    assert {
        "story_type",
        "first_seen_at",
        "last_seen_at",
        "last_event_at",
        "occurrence_count",
        "primary_object_type",
        "primary_object_value",
        "latest_fact_id",
        "latest_summary",
    } <= story_columns
    assert "raw_upload_default" not in policy_columns


def test_initialize_creates_current_query_indexes(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        fact_indexes = {row["name"] for row in conn.execute("pragma index_list(observed_facts)").fetchall()}
        story_indexes = {row["name"] for row in conn.execute("pragma index_list(observation_stories)").fetchall()}
        signature_indexes = {row["name"] for row in conn.execute("pragma index_list(error_signatures)").fetchall()}

    assert "idx_observed_facts_created_at" in fact_indexes
    assert "idx_observed_facts_conversation_occurred" in fact_indexes
    assert "idx_observed_facts_fact_type_created_at" in fact_indexes
    assert "idx_observed_facts_category_occurred_at" in fact_indexes
    assert "idx_observation_stories_attention_last_event" in story_indexes
    assert "idx_observation_stories_type_last_event" in story_indexes
    assert "idx_error_signatures_category_key" in signature_indexes
