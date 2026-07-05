from __future__ import annotations

import json
import sqlite3

from app.behavior_signals.common import loads
from app.behavior_signals.taxonomy import family_of


def row_to_signal(row: sqlite3.Row, include_groups: bool) -> dict:
    scope = loads(row["affected_scope_json"])
    signal_kind = row["signal_kind"]
    payload = {
        "signal_id": row["signal_id"],
        "signal_key": row["signal_key"],
        "signal_kind": signal_kind,
        "risk_family": family_of(signal_kind),
        "title": row["title"],
        "why_it_matters": row["why_it_matters"],
        "severity": row["severity"],
        "confidence": row["confidence"],
        "priority_score": row["priority_score"],
        "affected_scope": scope,
        "evidence_groups": json.loads(row["evidence_groups_json"] or "[]"),
        "linked_conversations": json.loads(row["linked_conversations_json"] or "[]"),
        "workspace_refs": scope.get("workspace_refs", []),
        "workspace_summary": scope.get("workspace_summary") or {"mode": "unknown", "label": "工作区未知", "count": 0},
        "usage_summary": loads(row["usage_summary_json"]),
        "enrichment_status_summary": loads(row["enrichment_status_summary_json"]),
        "suggested_actions": json.loads(row["suggested_actions_json"] or "[]"),
        "decision_state": row["decision_state"],
        "conclusion_code": row["decision_conclusion_code"] if "decision_conclusion_code" in row.keys() else None,
        "note": row["decision_note"] if "decision_note" in row.keys() else None,
        "snapshot_hash": row["snapshot_hash"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "last_event_at": row["last_event_at"],
        "occurrence_count": row["occurrence_count"],
        "latest_fact_id": row["latest_fact_id"],
        "latest_summary": row["latest_summary"],
    }
    if not include_groups:
        payload["evidence_groups"] = [_group_summary(group) for group in payload["evidence_groups"][:3]]
    return payload


def _group_summary(group: dict) -> dict:
    return {key: value for key, value in group.items() if key != "items"} | {"items": group.get("items", [])[:2]}
