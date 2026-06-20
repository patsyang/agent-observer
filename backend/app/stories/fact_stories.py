from __future__ import annotations

import sqlite3

from app.stories.common import _loads, _snapshot_hash, _story_id
from app.stories.evidence import _diagnostic_evidence_entries, _diagnostic_status_summary, _evidence_entries, _usage_summary
from app.stories.presentation import (
    _attention_state,
    _impact_objects,
    _normalized_risk_object_type,
    _public_story,
    _risk_conclusion,
    _severity_rank,
    _story_metadata,
    _usage_conclusion,
)
from app.stories.repository import _facts_by_ids, _write_story_row


def build_usage_stories(conn: sqlite3.Connection, reason: str) -> list[dict]:
    rows = conn.execute(
        """
        select session_id, activity_tag, sum(units) as units, count(*) as fact_count
        from usage_signals
        group by session_id, activity_tag
        having units >= 50 or activity_tag = 'unknown'
        order by units desc
        """
    ).fetchall()
    return [_usage_story_for_scope(conn, row, reason) for row in rows]


def build_usage_stories_for_facts(conn: sqlite3.Connection, fact_ids: list[str], reason: str) -> list[dict]:
    placeholders = ",".join("?" for _ in fact_ids)
    scopes = conn.execute(
        f"select distinct session_id, activity_tag from usage_signals where fact_id in ({placeholders})",
        fact_ids,
    ).fetchall()
    stories = []
    for scope in scopes:
        row = conn.execute(
            """
            select session_id, activity_tag, sum(units) as units, count(*) as fact_count
            from usage_signals
            where session_id = ? and activity_tag = ?
            group by session_id, activity_tag
            """,
            (scope["session_id"], scope["activity_tag"]),
        ).fetchone()
        if row is None or not (int(row["units"]) >= 50 or row["activity_tag"] == "unknown"):
            continue
        stories.append(_usage_story_for_scope(conn, row, reason))
    return stories


def build_risk_stories(conn: sqlite3.Connection, reason: str) -> list[dict]:
    rows = conn.execute(
        """
        select risk_type, object_type, severity, fact_id
        from risk_signals
        order by risk_type, object_type, fact_id
        """
    ).fetchall()
    groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        object_type = _normalized_risk_object_type(conn, row)
        if not object_type:
            continue
        key = (row["risk_type"], object_type)
        group = groups.setdefault(
            key,
            {"risk_type": row["risk_type"], "object_type": object_type, "fact_ids": [], "severity": row["severity"]},
        )
        group["fact_ids"].append(row["fact_id"])
        if _severity_rank(row["severity"]) > _severity_rank(group["severity"]):
            group["severity"] = row["severity"]
    stories = []
    for group in sorted(groups.values(), key=lambda item: (-len(item["fact_ids"]), item["risk_type"], item["object_type"])):
        facts = _facts_by_ids(conn, group["fact_ids"])
        story_key = f"risk:{group['risk_type']}:{group['object_type']}"
        stories.append(
            _upsert_fact_story(
                conn,
                story_key,
                reason,
                facts,
                _risk_conclusion(conn, group["risk_type"], group["object_type"], len(group["fact_ids"]), facts),
                ["核对风险对象、证据投影和是否需要发起白名单补证"],
                85 if group["severity"] == "high" else 70,
            )
        )
    return stories


def build_risk_stories_for_facts(conn: sqlite3.Connection, fact_ids: list[str], reason: str) -> list[dict]:
    placeholders = ",".join("?" for _ in fact_ids)
    affected = conn.execute(
        f"select risk_type, object_type, severity, fact_id from risk_signals where fact_id in ({placeholders})",
        fact_ids,
    ).fetchall()
    groups: dict[tuple[str, str], dict] = {}
    for row in affected:
        object_type = _normalized_risk_object_type(conn, row)
        if not object_type:
            continue
        groups[(row["risk_type"], object_type)] = {
            "risk_type": row["risk_type"],
            "object_type": object_type,
            "severity": row["severity"],
        }
    stories = []
    for group in sorted(groups.values(), key=lambda item: (item["risk_type"], item["object_type"])):
        stories.append(_risk_story_for_group(conn, group["risk_type"], group["object_type"], group["severity"], reason))
    return stories


def _usage_story_for_scope(conn: sqlite3.Connection, row: sqlite3.Row, reason: str) -> dict:
    fact_rows = conn.execute(
        """
        select of.*
        from usage_signals us
        join observed_facts of on of.fact_id = us.fact_id
        where us.session_id = ? and us.activity_tag = ?
        order by of.occurred_at desc, of.fact_id
        limit 20
        """,
        (row["session_id"], row["activity_tag"]),
    ).fetchall()
    return _upsert_fact_story(
        conn,
        f"usage:{row['session_id']}:{row['activity_tag']}",
        reason,
        list(reversed(fact_rows)),
        _usage_conclusion(row, int(row["fact_count"])),
        ["判断是否为历史回填、长会话或异常消耗；需要追溯时打开证据链查看关联会话"],
        min(90, 45 + int(row["units"]) // 10),
    )


def _risk_story_for_group(conn: sqlite3.Connection, risk_type: str, object_type: str, default_severity: str, reason: str) -> dict:
    if risk_type != "sensitive_object_touch":
        count_row = conn.execute(
            """
            select count(*) as count,
                   sum(case when severity = 'high' then 1 else 0 end) as high_count
            from risk_signals
            where risk_type = ? and object_type = ?
            """,
            (risk_type, object_type),
        ).fetchone()
        facts = conn.execute(
            """
            select of.*
            from risk_signals rs
            join observed_facts of on of.fact_id = rs.fact_id
            where rs.risk_type = ? and rs.object_type = ?
            order by of.occurred_at desc, of.fact_id
            limit 50
            """,
            (risk_type, object_type),
        ).fetchall()
        count = int(count_row["count"] or 0)
        severity = "high" if int(count_row["high_count"] or 0) else default_severity
        evidence_facts = list(reversed(facts))
    else:
        fact_ids_for_story, severity = _sensitive_risk_fact_ids(conn, risk_type, object_type, default_severity)
        count = len(fact_ids_for_story)
        evidence_facts = _facts_by_ids(conn, fact_ids_for_story[-50:])
    return _upsert_fact_story(
        conn,
        f"risk:{risk_type}:{object_type}",
        reason,
        evidence_facts,
        _risk_conclusion(conn, risk_type, object_type, count, evidence_facts),
        ["核对风险对象、证据投影和是否需要发起白名单补证"],
        85 if severity == "high" else 70,
    )


def _sensitive_risk_fact_ids(conn: sqlite3.Connection, risk_type: str, object_type: str, default_severity: str) -> tuple[list[str], str]:
    rows = conn.execute(
        """
        select risk_type, object_type, severity, fact_id
        from risk_signals
        where risk_type = ?
        order by fact_id
        """,
        (risk_type,),
    ).fetchall()
    fact_ids = []
    severity = default_severity
    for row in rows:
        if _normalized_risk_object_type(conn, row) != object_type:
            continue
        fact_ids.append(row["fact_id"])
        if _severity_rank(row["severity"]) > _severity_rank(severity):
            severity = row["severity"]
    return fact_ids, severity


def _upsert_fact_story(
    conn: sqlite3.Connection,
    story_key: str,
    reason: str,
    facts: list[sqlite3.Row],
    conclusion: str,
    suggested_actions: list[str],
    priority_score: int,
) -> dict:
    evidence_chain = []
    for fact in facts:
        evidence_chain.extend(_evidence_entries(conn, fact))
    evidence_refs = sorted(entry["evidence_ref"] for entry in evidence_chain)
    story_id = _story_id(story_key)
    diagnostic_entries = _diagnostic_evidence_entries(conn, story_id)
    evidence_chain.extend(diagnostic_entries)
    evidence_refs = sorted(set(evidence_refs + [entry["evidence_ref"] for entry in diagnostic_entries]))
    snapshot = {
        "reason": reason,
        "story_key": story_key,
        "evidence_chain": evidence_chain,
        "source_refs": [_loads(fact["source_refs_json"]) for fact in facts],
    }
    snapshot_hash = _snapshot_hash(snapshot)
    existing = conn.execute("select snapshot_hash, attention_state from observation_stories where story_id = ?", (story_id,)).fetchone()
    handling = conn.execute("select * from story_handling_states where story_id = ?", (story_id,)).fetchone()
    story = {
        "story_id": story_id,
        "story_key": story_key,
        "priority_score": priority_score,
        "evidence_refs": evidence_refs,
        "usage_summary": _usage_summary(conn, [fact["fact_id"] for fact in facts]),
        "diagnostic_status_summary": _diagnostic_status_summary(conn, story_id),
        "attention_state": _attention_state(existing, handling, snapshot_hash),
        "current_snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "conclusion": conclusion,
        "impact_objects": _impact_objects(conn, facts),
        "suggested_action": "；".join(suggested_actions),
    }
    story.update(_story_metadata(story_key, facts, evidence_chain))
    _write_story_row(conn, story)
    return _public_story(story, handling)
