from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter

from app.stories.common import _loads, _now
from app.stories.evidence import (
    _normalized_sensitive_object_type,
    _object_type_label,
    _sensitive_categories_for_projection,
)


def _story_metadata(story_key: str, facts: list[sqlite3.Row], evidence_chain: list[dict]) -> dict:
    dated_facts = sorted(
        [fact for fact in facts if fact is not None],
        key=lambda fact: (fact["occurred_at"], fact["fact_id"]),
    )
    first_seen = dated_facts[0]["occurred_at"] if dated_facts else _now()
    latest = dated_facts[-1] if dated_facts else None
    impact = _metadata_object(story_key, latest, evidence_chain)
    return {
        "story_type": story_key.split(":", 1)[0] if ":" in story_key else "unknown",
        "first_seen_at": first_seen,
        "last_seen_at": latest["occurred_at"] if latest else first_seen,
        "last_event_at": latest["occurred_at"] if latest else first_seen,
        "occurrence_count": len({fact["fact_id"] for fact in dated_facts}),
        "primary_object_type": impact["type"],
        "primary_object_value": impact["value"],
        "latest_fact_id": latest["fact_id"] if latest else None,
        "latest_summary": latest["summary"] if latest else "",
    }

def _metadata_object(story_key: str, latest: sqlite3.Row | None, evidence_chain: list[dict]) -> dict:
    parts = story_key.split(":")
    if parts and parts[0] == "command_timeout":
        return {"type": "command", "value": parts[-1] if len(parts) > 1 else "command_timeout"}
    if parts and parts[0] == "risk" and len(parts) >= 3:
        return {"type": parts[1], "value": parts[2]}
    for entry in evidence_chain:
        if entry.get("risk_object"):
            return {"type": str(entry.get("risk_object_type") or "risk"), "value": str(entry["risk_object"])}
    if latest is not None:
        return {"type": latest["fact_type"], "value": latest["category"]}
    return {"type": "unknown", "value": "unknown"}

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

def _error_conclusion(signature: sqlite3.Row | dict, hit_count: int | None = None) -> str:
    occurrences = hit_count if hit_count is not None else int(signature["occurrences"])
    count_text = "1" if occurrences == 1 else f"{occurrences:,}"
    return f"发现 {count_text} 条 Codex 工具执行失败命中，已记录错误指纹，建议核对是否复发。"

def _risk_type_label(value: str) -> str:
    labels = {
        "high_risk_operation": "高风险操作",
        "sensitive_object_touch": "敏感对象触达",
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

def _row_to_story(conn: sqlite3.Connection, row: sqlite3.Row, *, include_evidence_refs: bool = True) -> dict:
    handling = conn.execute("select * from story_handling_states where story_id = ?", (row["story_id"],)).fetchone()
    evidence_refs = json.loads(row["evidence_refs_json"])
    story = {
        "story_id": row["story_id"],
        "story_key": row["story_key"],
        "priority_score": row["priority_score"],
        "evidence_refs": evidence_refs if include_evidence_refs else [],
        "usage_summary": json.loads(row["usage_summary_json"]),
        "enrichment_status_summary": json.loads(row["enrichment_status_summary_json"]),
        "attention_state": row["attention_state"],
        "snapshot_hash": row["snapshot_hash"],
        "conclusion": row["conclusion"],
        "impact_objects": json.loads(row["impact_objects_json"]),
        "suggested_action": row["suggested_action"],
        "story_type": row["story_type"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "last_event_at": row["last_event_at"] or row["updated_at"],
        "occurrence_count": row["occurrence_count"],
        "primary_object_type": row["primary_object_type"],
        "primary_object_value": row["primary_object_value"],
        "latest_fact_id": row["latest_fact_id"],
        "latest_summary": row["latest_summary"],
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
