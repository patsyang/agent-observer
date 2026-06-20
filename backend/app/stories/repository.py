from __future__ import annotations

import sqlite3

from app.stories.common import _dumps, _loads, _now


def _remove_stale_error_stories(conn: sqlite3.Connection, active_story_ids: list[str]) -> None:
    if not active_story_ids:
        conn.execute("delete from observation_stories where story_key like 'error:%'")
        return
    placeholders = ",".join("?" for _ in active_story_ids)
    conn.execute(
        f"delete from observation_stories where story_key like 'error:%' and story_id not in ({placeholders})",
        active_story_ids,
    )

def _remove_stale_risk_stories(conn: sqlite3.Connection, active_story_ids: list[str]) -> None:
    if not active_story_ids:
        conn.execute("delete from observation_stories where story_key like 'risk:%'")
        return
    placeholders = ",".join("?" for _ in active_story_ids)
    conn.execute(
        f"delete from observation_stories where story_key like 'risk:%' and story_id not in ({placeholders})",
        active_story_ids,
    )

def _remove_stale_command_timeout_stories(conn: sqlite3.Connection, active_story_ids: list[str]) -> None:
    if not active_story_ids:
        conn.execute("delete from observation_stories where story_key like 'command_timeout:%'")
        return
    placeholders = ",".join("?" for _ in active_story_ids)
    conn.execute(
        f"delete from observation_stories where story_key like 'command_timeout:%' and story_id not in ({placeholders})",
        active_story_ids,
    )

def _write_story_row(conn: sqlite3.Connection, story: dict) -> None:
    conn.execute(
        """
        insert into observation_stories (
          story_id, story_key, priority_score, evidence_refs_json, usage_summary_json,
          diagnostic_status_summary_json, attention_state, current_snapshot_json, snapshot_hash,
          conclusion, impact_objects_json, suggested_action, story_type, first_seen_at, last_seen_at,
          last_event_at, occurrence_count, primary_object_type, primary_object_value,
          latest_fact_id, latest_summary, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(story_id) do update set
          priority_score = excluded.priority_score,
          evidence_refs_json = excluded.evidence_refs_json,
          usage_summary_json = excluded.usage_summary_json,
          diagnostic_status_summary_json = excluded.diagnostic_status_summary_json,
          attention_state = excluded.attention_state,
          current_snapshot_json = excluded.current_snapshot_json,
          snapshot_hash = excluded.snapshot_hash,
          conclusion = excluded.conclusion,
          impact_objects_json = excluded.impact_objects_json,
          suggested_action = excluded.suggested_action,
          story_type = excluded.story_type,
          first_seen_at = coalesce(observation_stories.first_seen_at, excluded.first_seen_at),
          last_seen_at = excluded.last_seen_at,
          last_event_at = excluded.last_event_at,
          occurrence_count = excluded.occurrence_count,
          primary_object_type = excluded.primary_object_type,
          primary_object_value = excluded.primary_object_value,
          latest_fact_id = excluded.latest_fact_id,
          latest_summary = excluded.latest_summary,
          updated_at = excluded.updated_at
        """,
        (
            story["story_id"],
            story["story_key"],
            story["priority_score"],
            _dumps(story["evidence_refs"]),
            _dumps(story["usage_summary"]),
            _dumps(story["diagnostic_status_summary"]),
            story["attention_state"],
            _dumps(story["current_snapshot"]),
            story["snapshot_hash"],
            story["conclusion"],
            _dumps(story["impact_objects"]),
            story["suggested_action"],
            story["story_type"],
            story["first_seen_at"],
            story["last_seen_at"],
            story["last_event_at"],
            story["occurrence_count"],
            story["primary_object_type"],
            story["primary_object_value"],
            story["latest_fact_id"],
            story["latest_summary"],
            _now(),
        ),
    )

def _facts_by_ids(conn: sqlite3.Connection, fact_ids: list[str]) -> list[sqlite3.Row]:
    if not fact_ids:
        return []
    placeholders = ",".join("?" for _ in fact_ids)
    return conn.execute(f"select * from observed_facts where fact_id in ({placeholders}) order by occurred_at desc, fact_id", fact_ids).fetchall()


def _related_facts(conn: sqlite3.Connection, conversation_ref: str | None, fallback_fact_id: str) -> list[sqlite3.Row]:
    if conversation_ref:
        rows = conn.execute(
            """
            select * from observed_facts
            where conversation_ref = ?
            order by occurred_at, fact_id
            """,
            (conversation_ref,),
        ).fetchall()
        if rows:
            return rows
    row = conn.execute("select * from observed_facts where fact_id = ?", (fallback_fact_id,)).fetchone()
    return [row] if row is not None else []
