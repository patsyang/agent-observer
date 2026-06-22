from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict

from app.behavior_signals.common import dumps, loads, now_iso, signal_id, snapshot_hash, window_cutoff
from app.behavior_signals.evidence import enrichment_status_summary, usage_summary
from app.behavior_signals.helpers import (
    failure_group as _failure_group,
    conversation_groups as _conversation_groups,
    enrichment_group as _enrichment_group,
    object_group as _object_group,
    directory_group as _directory_group,
    linked_conversations as _linked_conversations,
    remove_stale as _remove_stale,
    write_audit as _write_audit,
    normalize_note as _normalize_note,
    canonical_signature as _canonical_signature,
    signature_facts as _signature_facts,
    conversation_refs as _conversation_refs,
    primary_projection as _primary_projection,
    first_text as _first_text,
    exit_code_from_summary as _exit_code_from_summary,
    command_timeout_projection as _command_timeout_projection,
    risk_facts as _risk_facts,
    path_hint as _path_hint,
    top_directories as _top_directories,
    key_path_label as _key_path_label,
    high_confidence_sensitive as _high_confidence_sensitive,
    object_type_label as _object_type_label,
)

def rebuild_signals(conn: sqlite3.Connection, reason: str = "manual") -> dict:
    active: list[str] = []
    signals: list[dict] = []
    for builder in (
        _build_tool_failure_clusters,
        _build_command_timeouts,
        _build_workspace_change_bursts,
        _build_key_file_changes,
        _build_sensitive_object_touches,
    ):
        for item in builder(conn, reason):
            if item:
                active.append(item["signal_id"])
                signals.append(item)
    _remove_stale(conn, active)
    conn.commit()
    return {"reason": reason, "updated": len(signals), "signals": signals}


def update_signals_for_facts(conn: sqlite3.Connection, fact_ids: list[str], reason: str = "telemetry_ingest") -> dict:
    # Incremental correctness is less important than avoiding stale broad buckets; the rebuild is deterministic and bounded by local DB size.
    return rebuild_signals(conn, reason=reason)


def list_signals(conn: sqlite3.Connection, window: str = "all", page: int = 1, page_size: int = 20) -> dict:
    current_page = max(1, int(page or 1))
    limit = max(1, min(int(page_size or 20), 100))
    offset = (current_page - 1) * limit
    clauses = ["bs.decision_state != 'handled'"]
    params: list[str] = []
    cutoff = window_cutoff(window)
    if cutoff:
        clauses.append("coalesce(bs.last_event_at, bs.updated_at) >= ?")
        params.append(cutoff)
    where = f"where {' and '.join(clauses)}"
    total = conn.execute(
        f"""
        select count(*) as total
        from behavior_signals bs
        left join signal_decisions sd on sd.signal_id = bs.signal_id
        {where}
        """,
        params,
    ).fetchone()["total"]
    rows = conn.execute(
        f"""
        select bs.*, sd.conclusion_code as decision_conclusion_code, sd.note as decision_note
        from behavior_signals bs
        left join signal_decisions sd on sd.signal_id = bs.signal_id
        {where}
        order by bs.priority_score desc, coalesce(bs.last_event_at, bs.updated_at) desc, bs.signal_key
        limit ? offset ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return {
        "signals": [_row_to_signal(row, include_groups=False) for row in rows],
        "total": int(total),
        "page": current_page,
        "page_size": limit,
        "has_more": offset + len(rows) < int(total),
    }


def get_signal_detail(conn: sqlite3.Connection, signal_id_value: str) -> dict:
    row = conn.execute(
        """
        select bs.*, sd.conclusion_code as decision_conclusion_code, sd.note as decision_note
        from behavior_signals bs
        left join signal_decisions sd on sd.signal_id = bs.signal_id
        where bs.signal_id = ?
        """,
        (signal_id_value,),
    ).fetchone()
    if row is None:
        raise LookupError(signal_id_value)
    return _row_to_signal(row, include_groups=True)


def mark_signal_read(conn: sqlite3.Connection, signal_id_value: str) -> dict:
    return _set_decision(conn, signal_id_value, "read", None, None, "signal_read")


def handle_signal(conn: sqlite3.Connection, signal_id_value: str, conclusion_code: str | None, note: str | None = None) -> dict:
    if not conclusion_code or not conclusion_code.strip():
        raise ValueError("conclusion_code_required")
    return _set_decision(conn, signal_id_value, "handled", conclusion_code.strip(), _normalize_note(note), "signal_decision_recorded")


def _set_decision(
    conn: sqlite3.Connection,
    signal_id_value: str,
    state: str,
    conclusion_code: str | None,
    note: str | None,
    audit_action: str,
) -> dict:
    row = conn.execute("select * from behavior_signals where signal_id = ?", (signal_id_value,)).fetchone()
    if row is None:
        raise LookupError(signal_id_value)
    now = now_iso()
    conn.execute(
        """
        insert into signal_decisions (signal_id, decision_state, conclusion_code, note, updated_by, updated_at)
        values (?, ?, ?, ?, 'fixed-management-account', ?)
        on conflict(signal_id) do update set
          decision_state = excluded.decision_state,
          conclusion_code = excluded.conclusion_code,
          note = excluded.note,
          updated_by = excluded.updated_by,
          updated_at = excluded.updated_at
        """,
        (signal_id_value, state, conclusion_code, note, now),
    )
    conn.execute("update behavior_signals set decision_state = ?, updated_at = ? where signal_id = ?", (state, now, signal_id_value))
    _write_audit(conn, signal_id_value, audit_action, {"after_state": state, "conclusion_code": conclusion_code})
    conn.commit()
    return get_signal_detail(conn, signal_id_value)


def _decision_state(existing: sqlite3.Row | None, decision: sqlite3.Row | None, next_hash: str) -> str:
    if decision is None:
        return "unread"
    if decision["decision_state"] == "handled" and existing and existing["snapshot_hash"] != next_hash:
        return "needs_review"
    return str(decision["decision_state"] or "unread")


def _build_tool_failure_clusters(conn: sqlite3.Connection, reason: str) -> list[dict]:
    signatures = conn.execute("select * from error_signatures where category != 'command_timeout' order by signature_key").fetchall()
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for signature in signatures:
        groups[_canonical_signature(signature["signature_key"])].append(signature)
    results = []
    for canonical, rows in groups.items():
        facts = _signature_facts(conn, rows)
        if not facts or all(_command_timeout_projection(conn, fact["fact_id"]) for fact in facts):
            continue
        projections = [_primary_projection(conn, fact["fact_id"]) for fact in facts]
        tool = _first_text(projections, "tool_name", "tool", "name") or "Codex 工具"
        exit_code = _first_text(projections, "exit_code") or _exit_code_from_summary(facts[-1]["summary"])
        title = f"工具失败集中出现：{tool}{f' / exit_code {exit_code}' if exit_code else ''}"
        why = f"同类工具失败在 {len(_conversation_refs(facts)):,} 个会话中出现 {len(facts):,} 次，通常代表稳定失败模式或环境前置条件缺失。"
        signal_key = f"tool_failure_cluster:{canonical}"
        results.append(
            _upsert_signal(
                conn,
                signal_key=signal_key,
                signal_kind="tool_failure_cluster",
                title=title,
                why_it_matters=why,
                severity="high",
                confidence="high",
                priority_score=95,
                facts=facts,
                affected_scope={
                    "conversation_count": len(_conversation_refs(facts)),
                    "failure_count": len(facts),
                    "tool_names": [tool],
                    "exit_codes": [exit_code] if exit_code else [],
                },
                evidence_groups=[
                    _failure_group(conn, "failure", title, facts, projections),
                    *_conversation_groups(conn, facts, limit=4),
                    _enrichment_group(conn, signal_id(signal_key)),
                ],
                suggested_actions=["先看失败会话 Top，再补充工具失败上下文；若同一命令反复失败，优先修复环境或参数。"],
                reason=reason,
            )
        )
    return results


def _build_command_timeouts(conn: sqlite3.Connection, reason: str) -> list[dict]:
    rows = conn.execute(
        "select * from observed_facts where category in ('command_timeout', 'codex_error') order by occurred_at, fact_id"
    ).fetchall()
    groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    projections: dict[str, dict] = {}
    for row in rows:
        projection = _command_timeout_projection(conn, row["fact_id"])
        if not projection:
            continue
        projections[row["fact_id"]] = projection
        groups[(str(projection.get("workflow") or "unknown"), str(projection.get("run_id") or "unknown"))].append(row)
    signals = []
    for (workflow, run_id), facts in groups.items():
        latest = projections.get(facts[-1]["fact_id"], {})
        duration = latest.get("wall_time_seconds")
        title = f"命令超时：{workflow} / {run_id}"
        why = "命令超时会阻断工作流推进；按 run 定位后可以直接查看 run.json 和 workflow-event.jsonl。"
        signals.append(
            _upsert_signal(
                conn,
                signal_key=f"command_timeout:{workflow}:{run_id}",
                signal_kind="command_timeout",
                title=title,
                why_it_matters=why,
                severity="high",
                confidence="high" if workflow != "unknown" else "medium",
                priority_score=90,
                facts=facts,
                affected_scope={
                    "run_ids": [run_id],
                    "workflows": [workflow],
                    "timeout_count": len(facts),
                    "duration_seconds": duration,
                },
                evidence_groups=[_failure_group(conn, "failure", title, facts, [projections.get(f["fact_id"], {}) for f in facts])],
                suggested_actions=["打开该 run 的运行日志，确认超时节点、命令和最近一次用户输入。"],
                reason=reason,
            )
        )
    return signals


def _build_workspace_change_bursts(conn: sqlite3.Connection, reason: str) -> list[dict]:
    facts = _risk_facts(conn, "high_risk_operation", "workspace_file")
    by_conversation: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for fact in facts:
        by_conversation[fact["conversation_ref"] or "unknown"].append(fact)
    signals = []
    for conversation_ref, group in by_conversation.items():
        paths = [_path_hint(conn, fact) for fact in group]
        unique_paths = {path for path in paths if path}
        if len(group) < 20 and len(unique_paths) < 10:
            continue
        title = f"单会话工作区修改密集：{len(group):,} 次操作"
        why = "单个会话里短时间触发大量文件修改，适合优先核对是否符合本次任务边界。"
        signals.append(
            _upsert_signal(
                conn,
                signal_key=f"workspace_change_burst:{conversation_ref}",
                signal_kind="workspace_change_burst",
                title=title,
                why_it_matters=why,
                severity="medium",
                confidence="high",
                priority_score=75,
                facts=group,
                affected_scope={
                    "conversation_count": 1,
                    "operation_count": len(group),
                    "file_count": len(unique_paths),
                    "top_directories": _top_directories(paths),
                },
                evidence_groups=[
                    _object_group(conn, "conversation", f"会话 {conversation_ref}", group),
                    _directory_group(paths),
                ],
                suggested_actions=["打开关联会话，核对用户目标、修改文件 Top 和是否存在越界修改。"],
                reason=reason,
            )
        )
    return signals


def _build_key_file_changes(conn: sqlite3.Connection, reason: str) -> list[dict]:
    matched: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for fact in _risk_facts(conn, "high_risk_operation", None):
        path = _path_hint(conn, fact)
        label = _key_path_label(path)
        if label:
            matched[label].append(fact)
    signals = []
    for label, facts in matched.items():
        title = f"关键项目文件被修改：{label}"
        why = "关键配置、迁移、采集器或工作流入口变化会影响后续采集、运行和发布结果，需要独立确认。"
        paths = [_path_hint(conn, fact) for fact in facts]
        signals.append(
            _upsert_signal(
                conn,
                signal_key=f"key_file_change:{label}",
                signal_kind="key_file_change",
                title=title,
                why_it_matters=why,
                severity="high",
                confidence="medium" if not any(paths) else "high",
                priority_score=85,
                facts=facts,
                affected_scope={
                    "object_count": len({path for path in paths if path}) or len(facts),
                    "key_file_category": label,
                    "top_paths": [path for path, _ in Counter(paths).most_common(5) if path],
                },
                evidence_groups=[_object_group(conn, "object", label, facts)],
                suggested_actions=["确认这些关键文件修改是否由当前任务明确要求；必要时进入会话查看完整输入输出。"],
                reason=reason,
            )
        )
    return signals


def _build_sensitive_object_touches(conn: sqlite3.Connection, reason: str) -> list[dict]:
    rows = conn.execute(
        """
        select rs.object_type, of.*
        from risk_signals rs
        join observed_facts of on of.fact_id = rs.fact_id
        where rs.risk_type = 'sensitive_object_touch' and rs.severity = 'high'
        order by of.occurred_at, of.fact_id
        """
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        if _high_confidence_sensitive(conn, row["fact_id"]):
            groups[str(row["object_type"] or "sensitive_object")].append(row)
    signals = []
    for object_type, facts in groups.items():
        title = f"高可信敏感对象触达：{_object_type_label(object_type)}"
        signals.append(
            _upsert_signal(
                conn,
                signal_key=f"sensitive_object_touch:{object_type}",
                signal_kind="sensitive_object_touch",
                title=title,
                why_it_matters="高可信敏感对象进入会话上下文后，需确认是否符合最小暴露原则。",
                severity="high",
                confidence="high",
                priority_score=100,
                facts=facts,
                affected_scope={"object_count": len(facts), "object_types": [object_type], "conversation_count": len(_conversation_refs(facts))},
                evidence_groups=[_object_group(conn, "object", _object_type_label(object_type), facts)],
                suggested_actions=["进入关联会话确认敏感对象是否必要、是否已脱敏、是否需要清理本地记录。"],
                reason=reason,
            )
        )
    return signals


def _upsert_signal(
    conn: sqlite3.Connection,
    *,
    signal_key: str,
    signal_kind: str,
    title: str,
    why_it_matters: str,
    severity: str,
    confidence: str,
    priority_score: int,
    facts: list[sqlite3.Row],
    affected_scope: dict,
    evidence_groups: list[dict],
    suggested_actions: list[str],
    reason: str,
) -> dict:
    sid = signal_id(signal_key)
    facts = sorted(facts, key=lambda fact: (fact["occurred_at"], fact["fact_id"]))
    fact_ids = [fact["fact_id"] for fact in facts]
    linked = _linked_conversations(facts)
    evidence_groups = [group for group in evidence_groups if group and group.get("items")]
    snapshot = {
        "signal_key": signal_key,
        "signal_kind": signal_kind,
        "affected_scope": affected_scope,
        "evidence_groups": evidence_groups,
        "linked_conversations": linked,
        "suggested_actions": suggested_actions,
        "reason": reason,
    }
    digest = snapshot_hash(snapshot)
    existing = conn.execute("select snapshot_hash, decision_state, first_seen_at from behavior_signals where signal_id = ?", (sid,)).fetchone()
    decision = conn.execute("select * from signal_decisions where signal_id = ?", (sid,)).fetchone()
    decision_state = _decision_state(existing, decision, digest)
    now = now_iso()
    first_seen = existing["first_seen_at"] if existing else facts[0]["occurred_at"]
    latest = facts[-1]
    conn.execute(
        """
        insert into behavior_signals (
          signal_id, signal_key, signal_kind, title, why_it_matters, severity, confidence, priority_score,
          affected_scope_json, evidence_groups_json, linked_conversations_json, usage_summary_json,
          enrichment_status_summary_json, suggested_actions_json, decision_state, snapshot_hash,
          first_seen_at, last_seen_at, last_event_at, occurrence_count, latest_fact_id, latest_summary, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(signal_id) do update set
          signal_key = excluded.signal_key,
          signal_kind = excluded.signal_kind,
          title = excluded.title,
          why_it_matters = excluded.why_it_matters,
          severity = excluded.severity,
          confidence = excluded.confidence,
          priority_score = excluded.priority_score,
          affected_scope_json = excluded.affected_scope_json,
          evidence_groups_json = excluded.evidence_groups_json,
          linked_conversations_json = excluded.linked_conversations_json,
          usage_summary_json = excluded.usage_summary_json,
          enrichment_status_summary_json = excluded.enrichment_status_summary_json,
          suggested_actions_json = excluded.suggested_actions_json,
          decision_state = excluded.decision_state,
          snapshot_hash = excluded.snapshot_hash,
          first_seen_at = coalesce(behavior_signals.first_seen_at, excluded.first_seen_at),
          last_seen_at = excluded.last_seen_at,
          last_event_at = excluded.last_event_at,
          occurrence_count = excluded.occurrence_count,
          latest_fact_id = excluded.latest_fact_id,
          latest_summary = excluded.latest_summary,
          updated_at = excluded.updated_at
        """,
        (
            sid,
            signal_key,
            signal_kind,
            title,
            why_it_matters,
            severity,
            confidence,
            priority_score,
            dumps(affected_scope),
            dumps(evidence_groups),
            dumps(linked),
            dumps(usage_summary(conn, fact_ids)),
            dumps(enrichment_status_summary(conn, sid)),
            dumps(suggested_actions),
            decision_state,
            digest,
            first_seen,
            facts[0]["occurred_at"],
            latest["occurred_at"],
            len(facts),
            latest["fact_id"],
            latest["summary"],
            now,
        ),
    )
    return get_signal_detail(conn, sid)


def _row_to_signal(row: sqlite3.Row, include_groups: bool) -> dict:
    payload = {
        "signal_id": row["signal_id"],
        "signal_key": row["signal_key"],
        "signal_kind": row["signal_kind"],
        "title": row["title"],
        "why_it_matters": row["why_it_matters"],
        "severity": row["severity"],
        "confidence": row["confidence"],
        "priority_score": row["priority_score"],
        "affected_scope": loads(row["affected_scope_json"]),
        "evidence_groups": loads(row["evidence_groups_json"]).get("groups", []) if False else json.loads(row["evidence_groups_json"] or "[]"),
        "linked_conversations": json.loads(row["linked_conversations_json"] or "[]"),
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
