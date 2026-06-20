from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from app.db.connection import connect
from app.facts.service import query_facts


def test_concurrent_connections_initialize_schema_once_without_locking(tmp_path):
    db_path = tmp_path / "observer.sqlite"

    def read_collectors() -> int:
        with connect(db_path) as conn:
            return conn.execute("select count(*) from collectors").fetchone()[0]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: read_collectors(), range(24)))

    assert results == [0] * 24


def test_initialize_backfills_fact_list_fields_for_legacy_schema(tmp_path):
    db_path = tmp_path / "observer.sqlite"
    raw_conn = sqlite3.connect(db_path)
    raw_conn.executescript(
        """
        create table observed_facts (
          fact_id text primary key,
          source_event_id text not null default '',
          batch_id text not null,
          collector_id text not null,
          source text not null,
          fact_type text not null,
          category text not null,
          quality text not null,
          severity text not null,
          summary text not null,
          occurred_at text not null,
          promoted_to_story integer not null default 0,
          source_refs_json text not null,
          source_specific_json text not null,
          created_at text not null
        );
        create table evidence_projections (
          projection_id text primary key,
          fact_id text not null,
          category text not null,
          span text not null,
          raw_hash text not null,
          projection_json text not null,
          upload_raw integer not null default 0
        );
        """
    )
    raw_conn.execute(
        """
        insert into observed_facts (
          fact_id, source_event_id, batch_id, collector_id, source, fact_type, category,
          quality, severity, summary, occurred_at, source_refs_json, source_specific_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-prompt-001",
            "legacy-prompt-001",
            "legacy-batch",
            "collector-legacy",
            "codex",
            "content",
            "codex_prompt",
            "high",
            "low",
            "旧 Prompt 摘要",
            "2026-06-20T00:00:00+00:00",
            json.dumps({"conversation_ref": "legacy-conv"}),
            json.dumps({"codex_event_type": "message"}),
            "2026-06-20T00:00:01+00:00",
        ),
    )
    raw_conn.execute(
        """
        insert into evidence_projections (
          projection_id, fact_id, category, span, raw_hash, projection_json, upload_raw
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "proj-legacy-prompt-001",
            "legacy-prompt-001",
            "codex_prompt",
            "legacy:1",
            "hash-legacy",
            json.dumps({"role": "user", "content_length": 42}),
            0,
        ),
    )
    raw_conn.commit()
    raw_conn.close()

    with connect(db_path) as conn:
        facts = query_facts(conn, window="all", include_health=True)
        row = conn.execute(
            """
            select conversation_ref, session_ref, source_event_type, source_path_hash
            from observed_facts
            where fact_id = 'legacy-prompt-001'
            """
        ).fetchone()

    assert facts["facts"][0]["content_preview"] == "用户 Prompt，长度 42 字符，未上传原文"
    assert facts["facts"][0]["raw_status"] == "仅结构化字段"
    assert facts["facts"][0]["raw_available"] is False
    assert row["conversation_ref"] == "legacy-conv"
    assert row["source_event_type"] == "message"


def test_initialize_creates_fact_time_and_reference_indexes(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        index_names = {row["name"] for row in conn.execute("pragma index_list(observed_facts)").fetchall()}
        signature_index_names = {row["name"] for row in conn.execute("pragma index_list(error_signatures)").fetchall()}

    assert "idx_observed_facts_created_at" in index_names
    assert "idx_observed_facts_conversation_occurred" in index_names
    assert "idx_observed_facts_fact_type_created_at" in index_names
    assert "idx_observed_facts_category_occurred_at" in index_names
    assert "idx_error_signatures_category_key" in signature_index_names
