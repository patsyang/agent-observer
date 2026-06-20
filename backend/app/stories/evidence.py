from __future__ import annotations

import sqlite3

from app.evidence.presentation import (
    projection_preview,
    raw_available,
    raw_status_label,
    source_event_type,
    source_label,
)
from app.sensitivity import sensitive_matches_from_text
from app.stories.common import _loads


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

def _primary_projection(conn: sqlite3.Connection, fact_id: str) -> dict:
    row = conn.execute(
        "select projection_json from evidence_projections where fact_id = ? order by projection_id limit 1",
        (fact_id,),
    ).fetchone()
    return _loads(row["projection_json"]) if row is not None else {}

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
    matches = projection_json.get("sensitive_matches")
    if isinstance(matches, list):
        categories = {
            str(match.get("category"))
            for match in matches
            if isinstance(match, dict) and match.get("confidence") == "high" and match.get("category")
        }
        if categories:
            return sorted(categories)
    if not raw_content:
        return []
    return sorted({match["category"] for match in sensitive_matches_from_text(raw_content, "raw_content")})

def _normalized_sensitive_object_type(object_type: str, categories: list[str]) -> str:
    if object_type == "credential" and categories == ["auth"]:
        return "auth"
    if not object_type and categories:
        if any(category in {"token", "secret", "credential", "cookie"} for category in categories):
            return "credential"
        if "auth" in categories:
            return "auth"
    return object_type

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
