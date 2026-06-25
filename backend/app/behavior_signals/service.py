from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from app.behavior_signals.common import dumps, now_iso, signal_id, snapshot_hash
from app.time_ranges import range_bounds_iso
from app.behavior_signals.evidence import enrichment_status_summary, usage_summary
from app.behavior_signals.execution import build_execution_timeouts, build_tool_execution_failures
from app.behavior_signals.presentation import row_to_signal
from app.behavior_signals.workspace import signal_workspace_matches, workspace_summary, workspaces_from_facts
from app.behavior_signals.helpers import (
    conversation_groups as _conversation_groups,
    object_group as _object_group,
    directory_group as _directory_group,
    linked_conversations as _linked_conversations,
    remove_stale as _remove_stale,
    write_audit as _write_audit,
    normalize_note as _normalize_note,
    conversation_refs as _conversation_refs,
    primary_projection as _primary_projection,
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
        lambda db, why: build_tool_execution_failures(db, why, _upsert_signal),
        lambda db, why: build_execution_timeouts(db, why, _upsert_signal),
        _build_destructive_operations,
        _build_change_volume_anomalies,
        _build_key_file_changes,
        _build_sensitive_content_exposures,
    ):
        for item in builder(conn, reason):
            if item:
                active.append(item["signal_id"])
                signals.append(item)
    _remove_stale(conn, active)
    conn.commit()
    return {"reason": reason, "updated": len(signals), "signals": signals}


def update_signal_scope(
    conn: sqlite3.Connection,
    *,
    job_type: str,
    scope_type: str,
    scope_id: str,
    reason: str = "worker",
) -> dict:
    if job_type == "behavior_signal_rebuild" and scope_type == "global" and scope_id == "all":
        return rebuild_signals(conn, reason=reason)
    if job_type != "behavior_signal_update":
        raise ValueError("unsupported_processing_job")
    builders = {
        "execution": lambda: build_tool_execution_failures(conn, reason, _upsert_signal, canonical_scope=scope_id),
        "timeout": lambda: build_execution_timeouts(conn, reason, _upsert_signal, scope_key=scope_id),
        "file_change": lambda: [
            *_build_change_volume_anomalies(conn, reason, conversation_ref=scope_id),
            *_build_key_file_changes(conn, reason, conversation_ref=scope_id),
        ],
        "risk": lambda: _build_destructive_operations(conn, reason)
        if scope_id == "destructive_operation"
        else _build_sensitive_content_exposures(conn, reason, object_type=scope_id.removeprefix("sensitive_content_exposure:")),
    }
    if scope_type not in builders:
        raise ValueError("unsupported_processing_scope")
    signals = [item for item in builders[scope_type]() if item]
    conn.commit()
    return {"reason": reason, "updated": len(signals), "signals": signals}


def list_signals(
    conn: sqlite3.Connection,
    window: str = "all",
    workspace_query: str | None = None,
    agent_type: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    current_page = max(1, int(page or 1))
    limit = max(1, min(int(page_size or 20), 100))
    offset = (current_page - 1) * limit
    clauses = ["bs.decision_state != 'handled'"]
    params: list[str] = []
    cutoff, range_end = range_bounds_iso(window, start_at, end_at)
    if cutoff:
        clauses.append("coalesce(bs.last_event_at, bs.updated_at) >= ?")
        params.append(cutoff)
    if range_end:
        clauses.append("coalesce(bs.last_event_at, bs.updated_at) <= ?")
        params.append(range_end)
    if agent_type:
        clauses.append("latest.agent_type = ?")
        params.append(agent_type)
    where = f"where {' and '.join(clauses)}"
    latest_join = "left join observed_facts latest on latest.fact_id = bs.latest_fact_id"
    if not workspace_query:
        total = conn.execute(
            f"""
            select count(*) as total
            from behavior_signals bs
            left join signal_decisions sd on sd.signal_id = bs.signal_id
            {latest_join}
            {where}
            """,
            params,
        ).fetchone()["total"]
        rows = conn.execute(
            f"""
            select bs.*, sd.conclusion_code as decision_conclusion_code, sd.note as decision_note
            from behavior_signals bs
            left join signal_decisions sd on sd.signal_id = bs.signal_id
            {latest_join}
            {where}
            order by bs.priority_score desc, coalesce(bs.last_event_at, bs.updated_at) desc, bs.signal_key
            limit ? offset ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return {
            "signals": [row_to_signal(row, include_groups=False) for row in rows],
            "total": int(total),
            "page": current_page,
            "page_size": limit,
            "has_more": offset + len(rows) < int(total),
        }
    rows = conn.execute(
        f"""
        select bs.*, sd.conclusion_code as decision_conclusion_code, sd.note as decision_note
        from behavior_signals bs
        left join signal_decisions sd on sd.signal_id = bs.signal_id
        {latest_join}
        {where}
        order by bs.priority_score desc, coalesce(bs.last_event_at, bs.updated_at) desc, bs.signal_key
        """,
        params,
    ).fetchall()
    signals = [row_to_signal(row, include_groups=False) for row in rows]
    if workspace_query:
        signals = [item for item in signals if signal_workspace_matches(item, workspace_query)]
    page_items = signals[offset : offset + limit]
    return {
        "signals": page_items,
        "total": len(signals),
        "page": current_page,
        "page_size": limit,
        "has_more": offset + len(page_items) < len(signals),
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
    return row_to_signal(row, include_groups=True)


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


def _build_destructive_operations(conn: sqlite3.Connection, reason: str) -> list[dict]:
    facts = _risk_facts(conn, "destructive_operation", None)
    if not facts:
        return []
    title = f"破坏性操作出现：{len(facts):,} 次"
    return [
        _upsert_signal(
            conn,
            signal_key="destructive_operation_attempt",
            signal_kind="destructive_operation_attempt",
            title=title,
            why_it_matters="删除、权限变更、强制清理等操作可能影响工作区完整性，需要确认是否符合用户目标。",
            severity="high",
            confidence="high",
            priority_score=88,
            facts=facts,
            affected_scope={"operation_count": len(facts), "conversation_count": len(_conversation_refs(facts))},
            evidence_groups=[_object_group(conn, "object", "破坏性操作", facts)],
            suggested_actions=["查看命中会话和命令摘要，确认该操作是否由用户明确要求。"],
            reason=reason,
        )
    ]


def _build_change_volume_anomalies(conn: sqlite3.Connection, reason: str, conversation_ref: str | None = None) -> list[dict]:
    facts = _risk_facts(conn, "file_change", "workspace_file")
    by_conversation: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for fact in facts:
        if fact["conversation_ref"]:
            by_conversation[fact["conversation_ref"]].append(fact)
    signals = []
    for current_conversation_ref, group in by_conversation.items():
        if conversation_ref is not None and current_conversation_ref != conversation_ref:
            continue
        paths = []
        additions = 0
        deletions = 0
        for fact in group:
            projection = _primary_projection(conn, fact["fact_id"])
            changed = projection.get("changed_paths")
            if isinstance(changed, list):
                paths.extend(str(path).replace("\\", "/") for path in changed)
            elif path := _path_hint(conn, fact):
                paths.append(path)
            additions += int(projection.get("additions") or 0)
            deletions += int(projection.get("deletions") or 0)
        unique_paths = {path for path in paths if path}
        if len(unique_paths) < 20 and additions + deletions < 500:
            continue
        title = f"单会话变更量异常：{len(unique_paths):,} 个文件"
        why = "单个会话产生较大范围文件变更，需要核对是否符合本次任务边界和预期修改范围。"
        signals.append(
            _upsert_signal(
                conn,
                signal_key=f"change_volume_anomaly:{current_conversation_ref}",
                signal_kind="change_volume_anomaly",
                title=title,
                why_it_matters=why,
                severity="medium",
                confidence="high",
                priority_score=75,
                facts=group,
                affected_scope={"conversation_count": 1, "file_count": len(unique_paths), "additions": additions, "deletions": deletions, "top_directories": _top_directories(paths)},
                evidence_groups=[_object_group(conn, "conversation", f"会话 {conversation_ref}", group), _directory_group(paths)],
                suggested_actions=["打开命中会话，核对用户目标、变更文件 Top 和是否存在越界修改。"],
                reason=reason,
            )
        )
    return signals


def _build_key_file_changes(conn: sqlite3.Connection, reason: str, conversation_ref: str | None = None) -> list[dict]:
    target_labels = _key_file_labels_for_conversation(conn, conversation_ref) if conversation_ref else None
    matched: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for fact in _risk_facts(conn, "file_change", None):
        projection = _primary_projection(conn, fact["fact_id"])
        paths = projection.get("changed_paths")
        candidates = paths if isinstance(paths, list) else [_path_hint(conn, fact)]
        for path in candidates:
            label = _key_path_label(str(path))
            if target_labels is not None and label not in target_labels:
                continue
            if label:
                matched[label].append(fact)
                break
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


def _key_file_labels_for_conversation(conn: sqlite3.Connection, conversation_ref: str) -> set[str]:
    labels: set[str] = set()
    for fact in _risk_facts(conn, "file_change", None):
        if fact["conversation_ref"] != conversation_ref:
            continue
        projection = _primary_projection(conn, fact["fact_id"])
        paths = projection.get("changed_paths")
        candidates = paths if isinstance(paths, list) else [_path_hint(conn, fact)]
        for path in candidates:
            if label := _key_path_label(str(path)):
                labels.add(label)
    return labels


def _build_sensitive_content_exposures(conn: sqlite3.Connection, reason: str, object_type: str | None = None) -> list[dict]:
    rows = conn.execute(
        """
        select rs.object_type, of.*
        from risk_signals rs
        join observed_facts of on of.fact_id = rs.fact_id
        where rs.risk_type = 'sensitive_content_exposure' and rs.severity = 'high'
        order by of.occurred_at, of.fact_id
        """
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        if object_type and str(row["object_type"] or "sensitive_object") != object_type:
            continue
        if _high_confidence_sensitive(conn, row["fact_id"]):
            groups[str(row["object_type"] or "sensitive_object")].append(row)
    signals = []
    for object_type, facts in groups.items():
        title = f"敏感内容暴露：{_object_type_label(object_type)}"
        signals.append(
            _upsert_signal(
                conn,
                signal_key=f"sensitive_content_exposure:{object_type}",
                signal_kind="sensitive_content_exposure",
                title=title,
                why_it_matters="高可信敏感内容进入会话上下文后，需确认是否符合最小暴露原则。",
                severity="high",
                confidence="high",
                priority_score=100,
                facts=facts,
                affected_scope={"object_count": len(facts), "object_types": [object_type], "conversation_count": len(_conversation_refs(facts))},
                evidence_groups=[_object_group(conn, "object", _object_type_label(object_type), facts)],
                suggested_actions=["进入命中会话确认敏感内容是否必要、是否已脱敏、是否需要清理本地记录。"],
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
    linked = _linked_conversations(conn, facts)
    workspaces = workspaces_from_facts(facts)
    summary = workspace_summary(workspaces)
    affected_scope_payload = {**affected_scope, "workspace_refs": workspaces, "workspace_summary": summary}
    evidence_groups = [group for group in evidence_groups if group and group.get("items")]
    snapshot = {
        "signal_key": signal_key,
        "signal_kind": signal_kind,
        "affected_scope": affected_scope_payload,
        "evidence_groups": evidence_groups,
        "linked_conversations": linked,
        "workspace_refs": workspaces,
        "workspace_summary": summary,
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
            dumps(affected_scope_payload),
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



