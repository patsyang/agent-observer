from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime

from app.evidence.presentation import (
    projection_preview,
    raw_available,
    raw_status_label,
    source_event_type,
    source_label,
)
from app.sensitivity import sensitive_categories_from_text
from app.stories.filters import filter_story_rows
from app.stories.handling import handle_story, mark_story_read


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _loads(value: str) -> dict:
    return json.loads(value or "{}")


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _snapshot_hash(snapshot: dict) -> str:
    stable_snapshot = {key: value for key, value in snapshot.items() if key != "reason"}
    return hashlib.sha256(_dumps(stable_snapshot).encode("utf-8")).hexdigest()


def _story_id(story_key: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", story_key).strip("-").lower()
    return f"story-{slug[:80]}"


def rebuild_stories(conn: sqlite3.Connection, reason: str = "manual") -> dict:
    stories = []
    error_story_ids: list[str] = []
    for signatures in _group_error_signatures(
        conn.execute("select * from error_signatures order by signature_key").fetchall()
    ):
        story = _build_signature_story(conn, signatures, reason)
        if story:
            error_story_ids.append(story["story_id"])
        stories.append(story)
    stories.extend(_build_usage_stories(conn, reason))
    risk_stories = _build_risk_stories(conn, reason)
    stories.extend(risk_stories)
    _remove_stale_error_stories(conn, error_story_ids)
    _remove_stale_risk_stories(conn, [story["story_id"] for story in risk_stories if story])
    conn.commit()
    return {"reason": reason, "updated": len([story for story in stories if story]), "stories": [story for story in stories if story]}


def list_stories(conn: sqlite3.Connection, include_hidden: bool = False, window: str = "all", queue: str = "all") -> dict:
    where = "" if include_hidden else "where attention_state in ('active', 'needs_review')"
    rows = conn.execute(f"select * from observation_stories {where} order by priority_score desc, story_key").fetchall()
    filtered = filter_story_rows(conn, rows, window, queue)
    return {"stories": [_row_to_story(conn, row) for row in filtered]}


def get_story_detail(conn: sqlite3.Connection, story_id: str) -> dict:
    row = conn.execute("select * from observation_stories where story_id = ?", (story_id,)).fetchone()
    if row is None:
        raise LookupError(story_id)
    story = _row_to_story(conn, row)
    snapshot = _loads(row["current_snapshot_json"])
    snapshot["evidence_chain"] = _enrich_evidence_chain(conn, snapshot.get("evidence_chain", []))
    story["current_snapshot"] = snapshot
    story["recent_audit_summary"] = _recent_audit_summary(conn, story_id)
    return story


def _group_error_signatures(signatures: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    groups: dict[str, list[sqlite3.Row]] = {}
    for signature in signatures:
        groups.setdefault(_canonical_signature_key(signature["signature_key"]), []).append(signature)
    return [groups[key] for key in sorted(groups)]


def _canonical_signature_key(signature_key: str) -> str:
    parts = signature_key.split(":")
    if len(parts) >= 5 and re.fullmatch(r"[a-f0-9]{8}", parts[-1], re.IGNORECASE):
        return ":".join(parts[:-1] + [parts[1]])
    return signature_key


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


def _build_signature_story(conn: sqlite3.Connection, signatures: list[sqlite3.Row], reason: str) -> dict:
    facts_by_id: dict[str, sqlite3.Row] = {}
    for signature in signatures:
        error_fact = conn.execute("select * from observed_facts where fact_id = ?", (signature["fact_id"],)).fetchone()
        if error_fact is None:
            continue
        conversation_ref = _loads(error_fact["source_refs_json"]).get("conversation_ref")
        for fact in _related_facts(conn, conversation_ref, error_fact["fact_id"]):
            facts_by_id[fact["fact_id"]] = fact
    if not facts_by_id:
        return {}
    facts = sorted(facts_by_id.values(), key=lambda fact: (fact["occurred_at"], fact["fact_id"]))
    signature = _signature_summary(signatures)
    evidence_chain = []
    for fact in facts:
        evidence_chain.extend(_evidence_entries(conn, fact))
    diagnostic_entries = _diagnostic_evidence_entries(conn, _story_id(f"error:{signature['signature_key']}"))
    evidence_chain.extend(diagnostic_entries)
    evidence_refs = sorted(entry["evidence_ref"] for entry in evidence_chain)
    usage_summary = _usage_summary(conn, [fact["fact_id"] for fact in facts])
    impact_objects = _impact_objects(conn, facts)
    snapshot = {
        "reason": reason,
        "story_key": f"error:{signature['signature_key']}",
        "signature": {
            "signature_key": signature["signature_key"],
            "occurrences": int(signature["occurrences"]),
            "last_seen_at": signature["last_seen_at"],
        },
        "evidence_chain": evidence_chain,
        "source_refs": [_loads(fact["source_refs_json"]) for fact in facts],
    }
    snapshot_hash = _snapshot_hash(snapshot)
    story_key = snapshot["story_key"]
    story_id = _story_id(story_key)
    existing = conn.execute("select snapshot_hash, attention_state from observation_stories where story_id = ?", (story_id,)).fetchone()
    handling = conn.execute("select * from story_handling_states where story_id = ?", (story_id,)).fetchone()
    attention_state = _attention_state(existing, handling, snapshot_hash)
    story = {
        "story_id": story_id,
        "story_key": story_key,
        "priority_score": _priority_score(signature, facts),
        "evidence_refs": evidence_refs,
        "usage_summary": usage_summary,
        "diagnostic_status_summary": _diagnostic_status_summary(conn, story_id),
        "attention_state": attention_state,
        "current_snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "conclusion": _error_conclusion(signature),
        "impact_objects": impact_objects,
        "suggested_action": "查看证据链并选择处理结论",
    }
    conn.execute(
        """
        insert into observation_stories (
          story_id, story_key, priority_score, evidence_refs_json, usage_summary_json,
          diagnostic_status_summary_json, attention_state, current_snapshot_json, snapshot_hash,
          conclusion, impact_objects_json, suggested_action, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
          updated_at = excluded.updated_at
        """,
        (
            story_id,
            story_key,
            story["priority_score"],
            _dumps(evidence_refs),
            _dumps(usage_summary),
            _dumps(story["diagnostic_status_summary"]),
            attention_state,
            _dumps(snapshot),
            snapshot_hash,
            story["conclusion"],
            _dumps(impact_objects),
            story["suggested_action"],
            _now(),
        ),
    )
    return _public_story(story, handling)


def _signature_summary(signatures: list[sqlite3.Row]) -> dict:
    canonical = _canonical_signature_key(signatures[0]["signature_key"])
    return {
        "signature_key": canonical,
        "category": signatures[0]["category"],
        "fact_id": signatures[0]["fact_id"],
        "first_seen_at": min(signature["first_seen_at"] for signature in signatures),
        "last_seen_at": max(signature["last_seen_at"] for signature in signatures),
        "occurrences": sum(int(signature["occurrences"]) for signature in signatures),
    }


def _build_usage_stories(conn: sqlite3.Connection, reason: str) -> list[dict]:
    rows = conn.execute(
        """
        select session_id, activity_tag, sum(units) as units, group_concat(fact_id) as fact_ids
        from usage_signals
        group by session_id, activity_tag
        having units >= 50 or activity_tag = 'unknown'
        order by units desc
        """
    ).fetchall()
    stories = []
    for row in rows:
        fact_ids = [fact_id for fact_id in str(row["fact_ids"]).split(",") if fact_id]
        facts = _facts_by_ids(conn, fact_ids)
        story_key = f"usage:{row['session_id']}:{row['activity_tag']}"
        stories.append(
            _upsert_fact_story(
                conn,
                story_key,
                reason,
                facts,
                _usage_conclusion(row, len(facts)),
                ["判断是否为历史回填、长会话或异常消耗；需要追溯时打开证据链查看关联会话"],
                min(90, 45 + int(row["units"]) // 10),
            )
        )
    return stories


def _build_risk_stories(conn: sqlite3.Connection, reason: str) -> list[dict]:
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
        fact_ids = group["fact_ids"]
        facts = _facts_by_ids(conn, fact_ids)
        story_key = f"risk:{group['risk_type']}:{group['object_type']}"
        stories.append(
            _upsert_fact_story(
                conn,
                story_key,
                reason,
                facts,
                _risk_conclusion(conn, group["risk_type"], group["object_type"], len(fact_ids), facts),
                ["核对风险对象、证据投影和是否需要发起白名单补证"],
                85 if group["severity"] == "high" else 70,
            )
        )
    return stories


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
    attention_state = _attention_state(existing, handling, snapshot_hash)
    story = {
        "story_id": story_id,
        "story_key": story_key,
        "priority_score": priority_score,
        "evidence_refs": evidence_refs,
        "usage_summary": _usage_summary(conn, [fact["fact_id"] for fact in facts]),
        "diagnostic_status_summary": _diagnostic_status_summary(conn, story_id),
        "attention_state": attention_state,
        "current_snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "conclusion": conclusion,
        "impact_objects": _impact_objects(conn, facts),
        "suggested_action": "；".join(suggested_actions),
    }
    _write_story_row(conn, story)
    return _public_story(story, handling)


def _write_story_row(conn: sqlite3.Connection, story: dict) -> None:
    conn.execute(
        """
        insert into observation_stories (
          story_id, story_key, priority_score, evidence_refs_json, usage_summary_json,
          diagnostic_status_summary_json, attention_state, current_snapshot_json, snapshot_hash,
          conclusion, impact_objects_json, suggested_action, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            _now(),
        ),
    )


def _related_facts(conn: sqlite3.Connection, conversation_ref: str | None, fallback_fact_id: str) -> list[sqlite3.Row]:
    rows = conn.execute("select * from observed_facts order by occurred_at, fact_id").fetchall()
    related = [row for row in rows if conversation_ref and _loads(row["source_refs_json"]).get("conversation_ref") == conversation_ref]
    return related or [conn.execute("select * from observed_facts where fact_id = ?", (fallback_fact_id,)).fetchone()]


def _evidence_entries(conn: sqlite3.Connection, fact: sqlite3.Row) -> list[dict]:
    projections = conn.execute(
        "select * from evidence_projections where fact_id = ? order by projection_id", (fact["fact_id"],)
    ).fetchall()
    source_refs = _loads(fact["source_refs_json"])
    source_specific = _loads(fact["source_specific_json"])
    if not projections:
        return [
            {
                "evidence_ref": fact["fact_id"],
                "fact_id": fact["fact_id"],
                "category": fact["category"],
                "summary": fact["summary"],
                "quality": fact["quality"],
                "occurred_at": fact["occurred_at"],
                "fact_type": fact["fact_type"],
                "source_event_type": source_event_type(source_specific),
                "source_label": source_label(source_refs),
                "content_preview": fact["summary"],
                "raw_available": False,
                "raw_status": "无证据投影",
            }
        ]
    entries = []
    for projection in projections:
        projection_json = _loads(projection["projection_json"])
        entry = {
            "evidence_ref": projection["projection_id"],
            "fact_id": fact["fact_id"],
            "category": projection["category"],
            "summary": fact["summary"],
            "quality": fact["quality"],
            "occurred_at": fact["occurred_at"],
            "fact_type": fact["fact_type"],
            "source_event_type": source_event_type(source_specific),
            "source_label": source_label(source_refs),
            "content_preview": projection_preview(
                projection_json,
                projection["raw_content"],
                fact["summary"],
                projection["category"],
            ),
            "raw_available": raw_available(bool(projection["upload_raw"]), projection["raw_content"]),
            "raw_status": raw_status_label(bool(projection["upload_raw"]), projection["raw_content"]),
        }
        entry.update(_risk_evidence_fields(projection_json, projection["raw_content"]))
        entries.append(entry)
    return entries


def _enrich_evidence_chain(conn: sqlite3.Connection, entries: list[dict]) -> list[dict]:
    enriched = []
    for entry in entries:
        replacement = _evidence_entry_by_ref(conn, str(entry.get("evidence_ref", "")))
        enriched.append(replacement or entry)
    return enriched


def _evidence_entry_by_ref(conn: sqlite3.Connection, evidence_ref: str) -> dict | None:
    projection = conn.execute("select fact_id from evidence_projections where projection_id = ?", (evidence_ref,)).fetchone()
    if projection is not None:
        fact = conn.execute("select * from observed_facts where fact_id = ?", (projection["fact_id"],)).fetchone()
        if fact is None:
            return None
        return next((entry for entry in _evidence_entries(conn, fact) if entry["evidence_ref"] == evidence_ref), None)
    diagnostic = conn.execute(
        "select result_id, status, summary, created_at from diagnostic_results where result_id = ?",
        (evidence_ref,),
    ).fetchone()
    if diagnostic is None:
        return None
    return {
        "evidence_ref": diagnostic["result_id"],
        "fact_id": None,
        "category": "diagnostic_result",
        "summary": diagnostic["summary"],
        "quality": "high" if diagnostic["status"] == "succeeded" else "low",
        "occurred_at": diagnostic["created_at"],
        "fact_type": "diagnostic",
        "source_event_type": "diagnostic_result",
        "source_label": "白名单补证结果",
        "content_preview": diagnostic["summary"],
        "raw_available": False,
        "raw_status": "补证摘要",
    }


def _facts_by_ids(conn: sqlite3.Connection, fact_ids: list[str]) -> list[sqlite3.Row]:
    if not fact_ids:
        return []
    placeholders = ",".join("?" for _ in fact_ids)
    return conn.execute(f"select * from observed_facts where fact_id in ({placeholders}) order by occurred_at desc, fact_id", fact_ids).fetchall()


def _diagnostic_evidence_entries(conn: sqlite3.Connection, story_id: str) -> list[dict]:
    rows = conn.execute(
        "select result_id, status, summary, created_at from diagnostic_results where story_id = ? order by created_at",
        (story_id,),
    ).fetchall()
    return [
        {
            "evidence_ref": row["result_id"],
            "fact_id": None,
            "category": "diagnostic_result",
            "summary": row["summary"],
            "quality": "high" if row["status"] == "succeeded" else "low",
            "occurred_at": row["created_at"],
            "fact_type": "diagnostic",
            "source_event_type": "diagnostic_result",
            "source_label": "白名单补证结果",
            "content_preview": row["summary"],
            "raw_available": False,
            "raw_status": "补证摘要",
        }
        for row in rows
    ]


def _diagnostic_status_summary(conn: sqlite3.Connection, story_id: str) -> dict:
    row = conn.execute(
        "select status, reason_code from diagnostic_jobs where story_id = ? order by rowid desc limit 1",
        (story_id,),
    ).fetchone()
    if row is None:
        return {"status": "none", "reason_code": None}
    return {"status": row["status"], "reason_code": row["reason_code"]}


def _usage_summary(conn: sqlite3.Connection, fact_ids: list[str]) -> dict:
    if not fact_ids:
        return {"attributed_units": 0, "associated_units": 0, "no_usage_reason": "没有关联用量证据"}
    placeholders = ",".join("?" for _ in fact_ids)
    rows = conn.execute(f"select usage_kind, units from usage_signals where fact_id in ({placeholders})", fact_ids).fetchall()
    attributed = sum(row["units"] for row in rows if row["usage_kind"] == "attributed")
    associated = sum(row["units"] for row in rows if row["usage_kind"] == "associated")
    return {
        "attributed_units": attributed,
        "associated_units": associated,
        "no_usage_reason": None if rows else "没有关联用量证据",
    }


def _impact_objects(conn: sqlite3.Connection, facts: list[sqlite3.Row]) -> list[str]:
    error_summary = next((fact["summary"] for fact in facts if fact["fact_type"] == "error"), "")
    if "checkout workflow" in error_summary:
        return ["checkout workflow"]
    refs = []
    objects = []
    for fact in facts:
        fact_refs = _loads(fact["source_refs_json"])
        if fact_refs.get("conversation_ref"):
            refs.append(str(fact_refs["conversation_ref"]))
        objects.extend(_object_labels_for_fact(conn, fact))
    object_labels = sorted(set(objects))
    ref_labels = sorted(set(refs))
    if object_labels:
        if ref_labels:
            object_labels.append(f"Codex 对话 {len(ref_labels):,} 个")
        return object_labels[:5]
    if not ref_labels:
        return ["已观测的智能体工作流"]
    if all(_is_opaque_ref(item) for item in ref_labels):
        return [f"Codex 对话 {len(ref_labels):,} 个"]
    if len(ref_labels) > 5:
        return [f"Codex 对话 {len(ref_labels):,} 个"]
    return ref_labels


def _object_labels_for_fact(conn: sqlite3.Connection, fact: sqlite3.Row) -> list[str]:
    rows = conn.execute(
        "select projection_json, raw_content from evidence_projections where fact_id = ? order by projection_id",
        (fact["fact_id"],),
    ).fetchall()
    labels = []
    for row in rows:
        projection = _loads(row["projection_json"])
        object_type = str(projection.get("object_type") or "")
        categories = _sensitive_categories_for_projection(projection, row["raw_content"])
        if categories:
            object_type = _normalized_sensitive_object_type(object_type, categories)
        elif object_type in {"credential", "auth"}:
            continue
        if object_type:
            labels.append(_object_type_label(object_type))
    return labels


def _normalized_risk_object_type(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    object_type = str(row["object_type"] or "")
    if row["risk_type"] != "sensitive_object_touch":
        return object_type
    categories = _sensitive_categories_for_fact(conn, row["fact_id"])
    if not categories and object_type in {"credential", "auth"}:
        return ""
    return _normalized_sensitive_object_type(object_type, categories) or object_type or "unknown"


def _severity_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)


def _risk_conclusion(conn: sqlite3.Connection, risk_type: str, object_type: str, count: int, facts: list[sqlite3.Row]) -> str:
    risk_label = _risk_type_label(risk_type)
    object_label = _object_type_label(object_type)
    if risk_type != "sensitive_object_touch":
        return f"检测到 {count:,} 次{risk_label}，影响对象为{object_label}。"
    hit_summary = _sensitive_hit_summary(conn, facts)
    if hit_summary:
        return f"检测到 {count:,} 次{risk_label}，归类为{object_label}；主要命中 {hit_summary}。"
    return f"检测到 {count:,} 次{risk_label}，归类为{object_label}；本组缺少可读命中词，需要查看原文或重新采集。"


def _sensitive_hit_summary(conn: sqlite3.Connection, facts: list[sqlite3.Row]) -> str:
    counter: Counter[str] = Counter()
    for fact in facts:
        counter.update(_sensitive_categories_for_fact(conn, fact["fact_id"]))
    if not counter:
        return ""
    order = {"token": 0, "secret": 1, "cookie": 2, "credential": 3, "auth": 4}
    ranked = sorted(counter.items(), key=lambda item: (-item[1], order.get(item[0], 99), item[0]))
    return "、".join(f"{category} {count:,} 次" for category, count in ranked[:3])


def _sensitive_categories_for_fact(conn: sqlite3.Connection, fact_id: str) -> list[str]:
    categories: set[str] = set()
    rows = conn.execute(
        "select projection_json, raw_content from evidence_projections where fact_id = ? order by projection_id",
        (fact_id,),
    ).fetchall()
    for row in rows:
        categories.update(_sensitive_categories_for_projection(_loads(row["projection_json"]), row["raw_content"]))
    return sorted(categories)


def _risk_evidence_fields(projection_json: dict, raw_content: str | None = None) -> dict:
    if not _has_risk_projection(projection_json):
        return {}
    categories = _sensitive_categories_for_projection(projection_json, raw_content)
    object_type = _normalized_sensitive_object_type(str(projection_json.get("object_type") or ""), categories)
    if object_type in {"credential", "auth"} and not categories:
        return {}
    if not object_type:
        return {}
    fields = {
        "risk_object_type": str(object_type),
        "risk_object": _object_type_label(str(object_type)),
    }
    category_count = projection_json.get("category_count")
    if isinstance(category_count, int):
        fields["risk_category_count"] = category_count
    if categories:
        fields["sensitive_categories"] = categories
    return fields


def _has_risk_projection(projection_json: dict) -> bool:
    return bool(
        projection_json.get("object_type")
        or projection_json.get("risk_type")
        or projection_json.get("sensitive_categories")
        or projection_json.get("category_count")
    )


def _sensitive_categories_for_projection(projection_json: dict, raw_content: str | None) -> list[str]:
    categories = projection_json.get("sensitive_categories")
    if isinstance(categories, list):
        normalized = [str(category) for category in categories if str(category) != "sensitive_reference"]
        if normalized or not raw_content:
            return normalized
    if not raw_content:
        return []
    return sensitive_categories_from_text(raw_content)


def _normalized_sensitive_object_type(object_type: str, categories: list[str]) -> str:
    if object_type == "credential" and categories == ["auth"]:
        return "auth"
    if not object_type and categories:
        if any(category in {"token", "secret", "credential", "cookie"} for category in categories):
            return "credential"
        if "auth" in categories:
            return "auth"
    return object_type


def _error_conclusion(signature: sqlite3.Row) -> str:
    occurrences = int(signature["occurrences"])
    noun = "1 次" if occurrences == 1 else f"{occurrences:,} 次"
    return f"发现 {noun} Codex 工具执行失败，已生成错误指纹，建议核对是否复发。"


def _usage_conclusion(row: sqlite3.Row, fact_count: int) -> str:
    units = f"{int(row['units']):,}"
    activity = _activity_label(str(row["activity_tag"]))
    if fact_count > 1:
        return f"历史窗口内发现 {fact_count:,} 个 Codex 用量事件，累计约 {units} token，活动类型为 {activity}。"
    return f"发现 1 个 Codex 用量事件，约 {units} token，活动类型为 {activity}。"


def _activity_label(value: str) -> str:
    labels = {
        "codex_turn": "Codex 对话",
        "bug_fix": "缺陷修复",
        "implementation": "实现开发",
        "test_run": "测试运行",
        "unknown": "未识别活动",
    }
    return labels.get(value, value)


def _risk_type_label(value: str) -> str:
    labels = {
        "high_risk_operation": "高风险操作",
        "sensitive_object_touch": "敏感对象触达",
    }
    return labels.get(value, value)


def _object_type_label(value: str) -> str:
    labels = {
        "configuration": "配置",
        "file_path": "文件路径",
        "workspace_file": "工作区文件",
        "workspace": "工作区",
        "command": "命令",
        "auth": "认证对象",
        "credential": "认证凭据对象",
    }
    return labels.get(value, value)


def _is_opaque_ref(value: str) -> bool:
    return bool(re.search(r"\b(ref|proj|hash|fact|codex)[-:_]", value, re.IGNORECASE)) or bool(
        re.fullmatch(r"[a-f0-9]{12,}", value, re.IGNORECASE)
    )


def _priority_score(signature: sqlite3.Row, facts: list[sqlite3.Row]) -> int:
    severity_bonus = 30 if any(fact["severity"] == "high" for fact in facts) else 10
    return min(100, 50 + severity_bonus + int(signature["occurrences"]) * 5 + len(facts))


def _attention_state(existing: sqlite3.Row | None, handling: sqlite3.Row | None, snapshot_hash: str) -> str:
    if handling and handling["handling_state"] == "handled":
        if existing and existing["attention_state"] == "needs_review":
            return "needs_review"
        if existing and existing["snapshot_hash"] != snapshot_hash:
            return "needs_review"
        return "handled_hidden"
    return "active"


def _row_to_story(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    handling = conn.execute("select * from story_handling_states where story_id = ?", (row["story_id"],)).fetchone()
    story = {
        "story_id": row["story_id"],
        "story_key": row["story_key"],
        "priority_score": row["priority_score"],
        "evidence_refs": json.loads(row["evidence_refs_json"]),
        "usage_summary": json.loads(row["usage_summary_json"]),
        "diagnostic_status_summary": json.loads(row["diagnostic_status_summary_json"]),
        "attention_state": row["attention_state"],
        "snapshot_hash": row["snapshot_hash"],
        "conclusion": row["conclusion"],
        "impact_objects": json.loads(row["impact_objects_json"]),
        "suggested_action": row["suggested_action"],
    }
    return _public_story(story, handling)


def _public_story(story: dict, handling: sqlite3.Row | None) -> dict:
    story = dict(story)
    story["handling_state"] = handling["handling_state"] if handling else "unread"
    story["conclusion_code"] = handling["conclusion_code"] if handling else None
    story["handling_note"] = handling["note"] if handling else None
    return story


def _recent_audit_summary(conn: sqlite3.Connection, story_id: str) -> dict:
    rows = conn.execute(
        "select action, actor, metadata_json, created_at from audit_logs where object_id = ? order by rowid desc limit 3",
        (story_id,),
    ).fetchall()
    if not rows:
        return {"latest": "暂无审计记录", "events": []}
    events = [
        {
            "action": row["action"],
            "actor": row["actor"],
            "created_at": row["created_at"],
            "metadata": _loads(row["metadata_json"]),
        }
        for row in rows
    ]
    latest = events[0]
    return {"latest": f"{latest['action']} by {latest['actor']} at {latest['created_at']}", "events": events}
