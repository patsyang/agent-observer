from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from app.behavior_signals.common import dumps, now_iso, signal_id, snapshot_hash
from app.time_ranges import range_bounds_iso
from app.behavior_signals.evidence import enrichment_status_summary, usage_summary, usage_facts_for_signals
from app.behavior_signals.execution import build_execution_timeouts, build_tool_execution_failures
from app.behavior_signals.presentation import row_to_signal
from app.behavior_signals.taxonomy import (
    ALL_SIGNAL_KINDS,
    FAMILIES,
    UNCATEGORIZED,
    family_label,
    family_of,
    kinds_for_family,
)
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
    primary_projections_by_fact_id as _primary_projections_by_fact_id,
    risk_facts as _risk_facts,
    path_hint as _path_hint,
    top_directories as _top_directories,
    key_path_label as _key_path_label,
    high_confidence_sensitive as _high_confidence_sensitive,
    object_type_label as _object_type_label,
    failure_group as _failure_group,
    first_text as _first_text,
    exit_code_from_summary as _exit_code_from_summary,
    content_event_types as _content_event_types,
    tool_call_event_types as _tool_call_event_types,
    is_final_response as _is_final_response,
    LOOP_STUCK_WINDOW_MINUTES,
)

def rebuild_signals(conn: sqlite3.Connection, reason: str = "manual") -> dict:
    active: list[str] = []
    signals: list[dict] = []
    for builder in (
        lambda db, why: build_tool_execution_failures(db, why, _upsert_signal),
        lambda db, why: build_execution_timeouts(db, why, _upsert_signal),
        lambda db, why: detect_repeated_failures(db, why, _upsert_signal),
        lambda db, why: detect_loop_stuck(db, why, _upsert_signal),
        lambda db, why: detect_usage_anomalies(db, why, _upsert_signal),
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
        else _build_sensitive_content_exposures(conn, reason, conversation_ref=scope_id.removeprefix("sensitive_content_exposure:")),
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
    family: str | None = None,
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
    if family:
        _apply_family_filter(clauses, params, family)
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
    workspace_where = ""
    workspace_params: list[str] = []
    if workspace_query:
        workspace_where = " and bs.affected_scope_json like ?"
        workspace_params.append(f"%{workspace_query}%")
    rows = conn.execute(
        f"""
        select bs.*, sd.conclusion_code as decision_conclusion_code, sd.note as decision_note
        from behavior_signals bs
        left join signal_decisions sd on sd.signal_id = bs.signal_id
        {latest_join}
        {where}{workspace_where}
        order by bs.priority_score desc, coalesce(bs.last_event_at, bs.updated_at) desc, bs.signal_key
        """,
        [*params, *workspace_params],
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


def _apply_family_filter(clauses: list[str], params: list[str], family: str) -> None:
    """Append a signal_kind IN/NOT IN clause for the given risk_family."""
    if family == UNCATEGORIZED:
        known = list(ALL_SIGNAL_KINDS)
        clauses.append(f"bs.signal_kind not in ({','.join('?' for _ in known)})")
        params.extend(known)
        return
    family_kinds = kinds_for_family(family)
    if not family_kinds:
        # family has no mapped kinds → no rows match
        clauses.append("0")
        return
    clauses.append(f"bs.signal_kind in ({','.join('?' for _ in family_kinds)})")
    params.extend(family_kinds)


def signal_summary(
    conn: sqlite3.Connection,
    window: str = "all",
    agent_type: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict:
    """Aggregate unhandled behavior_signals by risk_family × severity.

    Uses the same window/agent filter as ``list_signals``; groups by
    ``signal_kind`` + ``severity`` in SQL, then rolls up to family via the
    taxonomy registry (single source of truth).
    """
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
    rows = conn.execute(
        f"""
        select bs.signal_kind as signal_kind, bs.severity as severity, count(*) as cnt
        from behavior_signals bs
        {latest_join}
        {where}
        group by bs.signal_kind, bs.severity
        """,
        params,
    ).fetchall()

    bucket: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        severity = (row["severity"] or "").lower()
        bucket[(family_of(row["signal_kind"]), severity)] += int(row["cnt"])

    severity_keys = ("high", "medium", "low")

    def _family_view(family_id: str, label: str) -> dict:
        by_severity = {key: 0 for key in severity_keys}
        total = 0
        for (fid, sev), count in bucket.items():
            if fid != family_id:
                continue
            by_severity[sev] = by_severity.get(sev, 0) + count
            total += count
        return {"id": family_id, "label": label, "total": total, "by_severity": by_severity}

    families_out = [_family_view(family["id"], family["label"]) for family in FAMILIES]
    # surface uncategorized only when present — it signals taxonomy drift
    if any(fid == UNCATEGORIZED for (fid, _) in bucket):
        families_out.append(_family_view(UNCATEGORIZED, family_label(UNCATEGORIZED)))

    return {
        "total": sum(item["total"] for item in families_out),
        "high_severity_total": sum(item["by_severity"].get("high", 0) for item in families_out),
        "families": families_out,
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
    # Increment decay_decision_count for decay-relevant conclusion codes
    if state == "handled" and conclusion_code in _DECAY_TRIGGER_CODES:
        conn.execute(
            "update behavior_signals set decision_count = coalesce(decision_count, 0) + 1 where signal_id = ?",
            (signal_id_value,),
        )
    # Recompute decision state with decay awareness
    existing = conn.execute("select snapshot_hash, decision_state from behavior_signals where signal_id = ?", (signal_id_value,)).fetchone()
    decision = conn.execute("select * from signal_decisions where signal_id = ?", (signal_id_value,)).fetchone()
    next_hash = row["snapshot_hash"]
    computed_state = _decision_state(existing, decision, next_hash, conn, signal_id_value)
    conn.execute(
        "update behavior_signals set decision_state = ?, updated_at = ? where signal_id = ?",
        (computed_state, now, signal_id_value),
    )
    _write_audit(conn, signal_id_value, audit_action, {"after_state": computed_state, "conclusion_code": conclusion_code})
    conn.commit()
    return get_signal_detail(conn, signal_id_value)


_DECAY_TRIGGER_CODES = frozenset({"expected_nonzero_exit", "accepted_risk"})
_DUPLICATE_CODE = "duplicate_signal"
_DECAY_THRESHOLD = 3
_DECAY_PRIORITY = 30
_NEEDS_REVIEW_COUNT_GROWTH = 0.50
_NEEDS_REVIEW_WINDOW_MINUTES = 60
_NEEDS_REVIEW_WINDOW_COUNT = 5


def apply_decision_decay(
    conn: sqlite3.Connection,
    signal_key: str,
    current_priority: int,
    current_occurrence_count: int,
) -> dict:
    """Apply decision-based decay to a signal's priority and review state.

    Returns a dict with keys:
      - priority: adjusted priority score
      - decision_state: updated decision state (may be 'needs_review')
      - decay_reason: reason for decay, or None
    """
    sid = signal_id(signal_key)
    # Read the decay decision counter stored in behavior_signals
    row = conn.execute(
        "select coalesce(decision_count, 0) as dc from behavior_signals where signal_id = ?",
        (sid,),
    ).fetchone()
    decay_count = row["dc"] if row else 0

    # 2. Apply priority decay: >= 3 same-signature decay decisions → priority=30
    decay_reason = None
    adjusted_priority = current_priority
    if decay_count >= _DECAY_THRESHOLD and current_priority > _DECAY_PRIORITY:
        adjusted_priority = _DECAY_PRIORITY
        decay_reason = f"decision_decay: {decay_count} consecutive {', '.join(sorted({'expected_nonzero_exit', 'accepted_risk'}))} decisions"

    # 3. Check needs_review triggers based on occurrence_count growth
    decision_state = "handled"  # only called after a decision; reflect review need
    if decay_count == 0:
        # No decay decisions yet — check occurrence growth trigger
        # We need the previous occurrence count; use a heuristic:
        # if current occurrence_count grew >= 50% from the last signal snapshot,
        # we flag needs_review. Since we can't easily compare historical counts
        # without a decisions audit trail, we rely on the snapshot_hash change
        # plus occurrence growth. For simplicity, check if occurrence_count
        # itself is >= threshold that implies growth.
        if current_occurrence_count >= _NEEDS_REVIEW_WINDOW_COUNT:
            # 1-hour window check: count recent facts for this signal
            recent_count = conn.execute(
                """
                select count(distinct of.fact_id)
                from behavior_signals bs
                join observed_facts of on of.conversation_ref = bs.affected_scope_json
                where bs.signal_id = ?
                  and coalesce(of.occurred_at, bs.updated_at) >= datetime('now', ? || ' hours')
                """,
                (sid, f"-{_NEEDS_REVIEW_WINDOW_MINUTES}"),
            ).fetchone()[0]
            if recent_count >= _NEEDS_REVIEW_WINDOW_COUNT:
                decision_state = "needs_review"
                if not decay_reason:
                    decay_reason = f"recent_burst: {recent_count} occurrences in {_NEEDS_REVIEW_WINDOW_MINUTES}min"

    return {
        "priority": adjusted_priority,
        "decision_state": decision_state,
        "decay_reason": decay_reason,
        "decay_count": decay_count,
    }


def _decision_state(
    existing: sqlite3.Row | None,
    decision: sqlite3.Row | None,
    next_hash: str,
    conn: sqlite3.Connection | None = None,
    signal_id_value: str | None = None,
) -> str:
    if decision is None:
        return "unread"
    if decision["decision_state"] == "handled" and existing and existing["snapshot_hash"] != next_hash:
        # Check occurrence_count growth trigger for needs_review
        if conn is not None and signal_id_value is not None:
            row = conn.execute(
                "select occurrence_count, decision_state from behavior_signals where signal_id = ?",
                (signal_id_value,),
            ).fetchone()
            if row is not None:
                prev_state = row["decision_state"]
                occ = row["occurrence_count"] or 0
                # If previously 'read'/'handled' and occurrence grew >= 50%,
                # escalate to needs_review
                if prev_state in ("read", "handled") and occ >= 2:
                    return "needs_review"
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


def _build_sensitive_content_exposures(conn: sqlite3.Connection, reason: str, conversation_ref: str | None = None) -> list[dict]:
    """按任务（会话）聚合敏感内容暴露——每个任务的敏感触碰是一条可结案信号。

    不再按全局 object_type 聚合（那是永远敞口的大类，无法处理）。
    每个会话里 agent 触碰的所有敏感类型（邮箱+手机+凭据…）合成一条信号，
    任务结束 → 不再进新事件 → 稳定 → 可处理。
    """
    rows = conn.execute(
        """
        select rs.object_type, of.*
        from risk_signals rs
        join observed_facts of on of.fact_id = rs.fact_id
        where rs.risk_type = 'sensitive_content_exposure' and rs.severity = 'high'
        order by of.occurred_at, of.fact_id
        """
    ).fetchall()
    seen: set[str] = set()
    deduped: list[sqlite3.Row] = []
    for row in rows:
        if row["fact_id"] in seen:
            continue
        seen.add(row["fact_id"])
        deduped.append(row)
    rows = deduped
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        conv = row["conversation_ref"] or ""
        if conversation_ref and conv != conversation_ref:
            continue
        if not conv:
            continue
        if _high_confidence_sensitive(conn, row["fact_id"]):
            groups[conv].append(row)
    signals = []
    for conv, facts in groups.items():
        object_types = sorted({str(r["object_type"] or "sensitive_object") for r in facts})
        type_labels = "、".join(_object_type_label(ot) for ot in object_types)
        evidence = []
        for ot in object_types:
            ot_facts = [f for f in facts if str(f["object_type"] or "sensitive_object") == ot]
            if ot_facts:
                evidence.append(_object_group(conn, "object", _object_type_label(ot), ot_facts))
        signals.append(
            _upsert_signal(
                conn,
                signal_key=f"sensitive_content_exposure:{conv}",
                signal_kind="sensitive_content_exposure",
                title=f"任务中触达敏感内容：{type_labels}",
                why_it_matters="Agent 在执行此任务时触碰了敏感内容，需确认该数据访问是否符合预期。",
                severity="high",
                confidence="high",
                priority_score=100,
                facts=facts,
                affected_scope={
                    "object_count": len(facts),
                    "object_types": object_types,
                    "conversation_count": 1,
                    "conversation_ref": conv,
                },
                evidence_groups=evidence,
                suggested_actions=["查看命中任务，确认敏感内容的访问是否必要、是否有安全风险。"],
                reason=reason,
            )
        )
    return signals


def detect_repeated_failures(
    conn: sqlite3.Connection,
    reason: str,
    upsert_signal,
) -> list[dict]:
    """Detect signatures that repeat >= 3 times within the same conversation.

    Excludes:
    - Signatures already classified as workflow_gate_blocked
    - Signatures with accepted_risk or expected_nonzero_exit conclusion
    """
    # Load conclusion codes that should be excluded
    excluded_codes = {"accepted_risk", "expected_nonzero_exit"}
    handled = conn.execute(
        "select signal_id, conclusion_code from signal_decisions where decision_state = 'handled'"
    ).fetchall()
    excluded_signal_ids: set[str] = {
        row["signal_id"] for row in handled if (row["conclusion_code"] or "").lower() in excluded_codes
    }

    # Build a set of signature_keys whose facts are tied to excluded signals.
    # We match via behavior_signals.signal_key (the raw key) which corresponds
    # to error_signature_facts.signature_key.
    excluded_sig_keys: set[str] = set()
    if excluded_signal_ids:
        # For each excluded signal, find its signal_key, then find all
        # error_signature_facts that share that key.
        for sid in excluded_signal_ids:
            row = conn.execute(
                "select signal_key from behavior_signals where signal_id = ?", (sid,)
            ).fetchone()
            if row:
                excluded_sig_keys.add(row["signal_key"])

    # Also check risk_signals table for accepted_risk / expected_nonzero_exit risk_type
    excluded_risk_fact_ids: set[str] = set()
    risk_rows = conn.execute(
        """
        select rs.fact_id
        from risk_signals rs
        where rs.risk_type in ('accepted_risk', 'expected_nonzero_exit')
        """
    ).fetchall()
    excluded_risk_fact_ids = {row["fact_id"] for row in risk_rows}

    # Find signatures with >= 3 occurrences
    signatures = conn.execute(
        """
        select signature_key, category, occurrences
        from error_signatures
        where occurrences >= 3
          and category in ('tool_execution_failure', 'workflow_step_failure')
        order by occurrences desc, signature_key
        """
    ).fetchall()

    results: list[dict] = []
    for sig in signatures:
        sig_key = sig["signature_key"]
        # Skip if signature already excluded by decision
        if sig_key in excluded_sig_keys:
            continue

        # Fetch facts for this signature
        facts = conn.execute(
            """
            select of.*
            from error_signature_facts esf
            join observed_facts of on of.fact_id = esf.fact_id
            where esf.signature_key = ?
            order by of.occurred_at, of.fact_id
            """,
            (sig_key,),
        ).fetchall()

        if not facts:
            continue

        # Skip if all facts are from accepted_risk / expected_nonzero_exit risk signals
        if excluded_risk_fact_ids and all(f["fact_id"] in excluded_risk_fact_ids for f in facts):
            continue

        # Group by conversation to detect within-conversation repetition
        by_conversation: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for fact in facts:
            conv = fact["conversation_ref"] or fact["session_ref"] or "unknown-conversation"
            by_conversation[conv].append(fact)

        for conv_ref, group in by_conversation.items():
            if len(group) < 3:
                continue

            projection_map = _primary_projections_by_fact_id(conn, [fact["fact_id"] for fact in group])
            projections = [projection_map.get(fact["fact_id"], {}) for fact in group]

            tool = _first_text(projections, "tool_name", "tool", "name") or "工具调用"
            exit_code = _first_text(projections, "exit_code") or _exit_code_from_summary(group[-1]["summary"] or "")

            # Check if any fact is from a workflow_gate_blocked classification
            # by examining the reason stored in behavior_signals
            gate_blocked = False
            for fact in group:
                # Check via risk_signals table for workflow_gate_blocked
                gate_row = conn.execute(
                    """
                    select rs.risk_type from risk_signals rs
                    join observed_facts of on of.fact_id = rs.fact_id
                    where of.fact_id = ? and rs.risk_type = 'workflow_gate_blocked'
                    limit 1
                    """,
                    (fact["fact_id"],),
                ).fetchone()
                if gate_row:
                    gate_blocked = True
                    break

            if gate_blocked:
                continue

            title = f"Agent 重复犯错：{tool} 在同一会话中失败 {len(group):,} 次"
            results.append(
                upsert_signal(
                    conn,
                    signal_key=f"repeated_tool_failure:{conv_ref}:{sig_key}",
                    signal_kind="repeated_tool_failure",
                    title=title,
                    why_it_matters=f"同一工具调用在会话内重复失败 {len(group):,} 次，说明问题不在偶发，需要定位根本原因并防止反复犯错。",
                    severity="high",
                    confidence="high",
                    priority_score=80,
                    facts=group,
                    affected_scope={
                        "conversation_count": 1,
                        "occurrence_count": len(group),
                        "signature_key": sig_key,
                        "tool_names": [tool],
                        "exit_codes": [exit_code] if exit_code else [],
                        "conversation_ref": conv_ref,
                    },
                    evidence_groups=[
                        _failure_group(conn, "repeated_failure", "重复失败事件", group, projections),
                    ],
                    suggested_actions=[
                        f"打开会话 {conv_ref}，检查 {tool} 的失败原因和最近输入；确认是否需要修正命令或环境。",
                    ],
                    reason=reason,
                )
            )

    return results


def detect_loop_stuck(
    conn: sqlite3.Connection,
    reason: str,
    upsert_signal,
) -> list[dict]:
    """Detect agent loops: tool calls without new content events in a 10-minute window.

    Triggers when:
    - Same conversation has tool calls (function_call / function_call_output)
    - But no new content events (agent_prompt / agent_response / agent_reasoning)
      within a 10-minute window based on occurred_at.

    Does NOT trigger:
    - Conversations that ended normally (have a final agent_response)
    - Idle conversations (no events at all)
    """
    from datetime import datetime, timedelta, timezone

    content_types = _content_event_types()
    tool_types = _tool_call_event_types()

    # Fetch all content events and tool call events, ordered by conversation and time.
    # Match by category only: source_event_type values in DB are granular (e.g.
    # 'response_item:function_call') and don't include the bare values like
    # 'function_call' or 'agent_response', so category is the reliable filter.
    ct_placeholders = ",".join("?" for _ in content_types)
    tc_placeholders = ",".join("?" for _ in tool_types)
    sql = (
        "select fact_id, fact_type, category, source_specific_json,"
        " source_event_type, summary, occurred_at,"
        " conversation_ref, session_ref"
        " from observed_facts"
        " where ("
        "   (fact_type = 'content' and category IN ({ct}))"
        "   OR category IN ({tc})"
        "  )"
        " order by conversation_ref, occurred_at, fact_id"
    ).format(ct=ct_placeholders, tc=tc_placeholders)
    rows = conn.execute(sql, list(content_types) + list(tool_types)).fetchall()

    if not rows:
        return []

    # Group by conversation
    by_conv: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        conv = row["conversation_ref"] or row["session_ref"] or "unknown-conversation"
        by_conv[conv].append(row)

    results: list[dict] = []
    window = timedelta(minutes=LOOP_STUCK_WINDOW_MINUTES)

    for conv_ref, events in by_conv.items():
        # Sort by occurred_at
        events.sort(key=lambda r: (r["occurred_at"] or "", r["fact_id"]))

        content_events = [e for e in events if e["category"] in content_types]
        tool_events = [e for e in events if e["category"] in tool_types]

        # Idle: no events at all
        if not content_events and not tool_events:
            continue

        # Normal end: has a final agent_response
        has_final = any(_is_final_response(e) for e in content_events)
        if has_final:
            continue

        # Need tool events to detect loop (tool calls without content = stuck)
        if not tool_events:
            continue

        # Check if there's a 10-minute window with tool calls but no new content
        # Strategy: for each tool event, look back 10 minutes.
        # If there are tool events in that window but no content event appeared, it's stuck.
        # More precisely: find the gap between last content event and most recent tool event.
        if not content_events:
            # No content events at all, but tool events exist -> likely stuck
            # Use the last tool event as the "stuck" point
            last_tool = tool_events[-1]
            first_tool = tool_events[0]
            # Calculate time span
            try:
                t_first = datetime.fromisoformat(first_tool["occurred_at"])
                t_last = datetime.fromisoformat(last_tool["occurred_at"])
                span = t_last - t_first
            except (ValueError, TypeError):
                continue

            if span >= window:
                # Long span of tool calls with zero content = definitely stuck
                results.append(_make_loop_stuck_signal(
                    conn, upsert_signal, conv_ref, tool_events, reason, span
                ))
            elif len(tool_events) >= 3:
                # Multiple tool calls with no content at all is suspicious
                results.append(_make_loop_stuck_signal(
                    conn, upsert_signal, conv_ref, tool_events, reason, span
                ))
            continue

        # Has content events + tool events: check for gaps
        # Walk through content events and see if tool events accumulated during gaps
        last_content_time = None
        for ce in content_events:
            try:
                last_content_time = datetime.fromisoformat(ce["occurred_at"])
            except (ValueError, TypeError):
                continue

        # Check the tail: tool events after the last content event
        tail_tools = []
        for te in tool_events:
            try:
                t = datetime.fromisoformat(te["occurred_at"])
                if last_content_time and t > last_content_time:
                    tail_tools.append(te)
            except (ValueError, TypeError):
                continue

        if len(tail_tools) >= 3:
            # 3+ tool calls after last content event = loop stuck
            try:
                t_first = datetime.fromisoformat(tail_tools[0]["occurred_at"])
                t_last = datetime.fromisoformat(tail_tools[-1]["occurred_at"])
                span = t_last - t_first
            except (ValueError, TypeError):
                span = window
            results.append(_make_loop_stuck_signal(
                conn, upsert_signal, conv_ref, tail_tools, reason, span
            ))
            continue

        # Check for gaps between content events where tools accumulated
        content_times = []
        for ce in content_events:
            try:
                content_times.append(datetime.fromisoformat(ce["occurred_at"]))
            except (ValueError, TypeError):
                continue

        for i in range(len(content_times) - 1):
            gap_start = content_times[i]
            gap_end = content_times[i + 1]
            gap = gap_end - gap_start
            if gap < window:
                continue
            # Count tool events in this gap
            gap_tools = []
            for te in tool_events:
                try:
                    t = datetime.fromisoformat(te["occurred_at"])
                    if gap_start < t < gap_end:
                        gap_tools.append(te)
                except (ValueError, TypeError):
                    continue
            if len(gap_tools) >= 3:
                results.append(_make_loop_stuck_signal(
                    conn, upsert_signal, conv_ref, gap_tools, reason, gap
                ))

    return results


def detect_usage_anomalies(
    conn: sqlite3.Connection,
    reason: str,
    upsert_signal,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Detect usage anomalies at runtime: usage_spike, low_cache_hit_rate, unknown_usage_dominant.

    Thresholds:
    - usage_spike: single fact input_tokens + output_tokens > 500_000, priority=70.
      Reports the largest single call per conversation (NOT cumulative session total).
      500K threshold avoids noise from normal context-window-sized calls (128K-200K).
    - low_cache_hit_rate: input_tokens > 10_000 AND cache_hit_rate < 10%, priority=65
    - unknown_usage_dominant: within 1-hour window, activity_tag=unknown占比 > 50%, priority=60

    ``now`` 用于注入参考时间，默认取当前 UTC 时间。测试通过传入跨小时边界的
    固定时间点，可稳定复现滑动窗口语义。
    """
    from datetime import datetime, timedelta, timezone

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # Check if promoted_to_signal column exists in usage_signals
    col_check = conn.execute("pragma table_info(usage_signals)").fetchall()
    has_promoted = any(row["name"] == "promoted_to_signal" for row in col_check)

    if has_promoted:
        # Collect only usage facts not yet promoted to a signal
        unused_usage_facts = conn.execute(
            """
            select us.fact_id, us.input_tokens, us.output_tokens, us.total_tokens,
                   us.cached_input_tokens, us.cache_observed, us.activity_tag,
                   us.conversation_id, us.session_id, us.account_ref,
                   us.project_ref, us.unit_basis, us.observability_level,
                   of.occurred_at, of.conversation_ref, of.session_ref, of.agent_type
            from usage_signals us
            join observed_facts of on of.fact_id = us.fact_id
            where us.promoted_to_signal = 0
            order by of.occurred_at
            """
        ).fetchall()
    else:
        # Fallback: get all usage facts when column doesn't exist
        unused_usage_facts = conn.execute(
            """
            select us.fact_id, us.input_tokens, us.output_tokens, us.total_tokens,
                   us.cached_input_tokens, us.cache_observed, us.activity_tag,
                   us.conversation_id, us.session_id, us.account_ref,
                   us.project_ref, us.unit_basis, us.observability_level,
                   of.occurred_at, of.conversation_ref, of.session_ref, of.agent_type
            from usage_signals us
            join observed_facts of on of.fact_id = us.fact_id
            order by of.occurred_at
            """
        ).fetchall()

    if not unused_usage_facts:
        return []

    results: list[dict] = []

    # --- usage_spike: single call with input_tokens + output_tokens > 500,000 ---
    # Threshold raised from 100K to 500K because modern LLMs have 128K-200K context
    # windows; a single call near the context limit is normal, not a risk.
    # 500K+ indicates potential loops, huge file ingestion, or runaway processes.
    # Key fix: report the LARGEST single call, NOT cumulative session total.
    SPIKE_THRESHOLD = 500_000
    spike_rows = []
    for row in unused_usage_facts:
        inp = int(row["input_tokens"] or 0)
        outp = int(row["output_tokens"] or 0)
        if inp + outp > SPIKE_THRESHOLD:
            spike_rows.append(row)

    if spike_rows:
        # Group by conversation for context, but report the largest single call
        signals_by_conv: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in spike_rows:
            conv = r["conversation_ref"] or r["session_ref"] or "global"
            signals_by_conv[conv].append(r)

        for conv_ref, group in signals_by_conv.items():
            # Find the largest single call in this conversation
            max_row = max(group, key=lambda r: int(r["input_tokens"] or 0) + int(r["output_tokens"] or 0))
            max_total = int(max_row["input_tokens"] or 0) + int(max_row["output_tokens"] or 0)
            title = (
                f"用量突增：单次调用 {max_total:,} tokens"
                f"（input={int(max_row['input_tokens'] or 0):,}, output={int(max_row['output_tokens'] or 0):,}）"
                f"，会话内 {len(group)} 次超阈值"
            )
            # Fetch full observed_facts rows for evidence groups
            spike_conv_facts = []
            for r in group:
                full = conn.execute("select * from observed_facts where fact_id = ?", (r["fact_id"],)).fetchone()
                if full:
                    spike_conv_facts.append(dict(full))
            results.append(
                upsert_signal(
                    conn,
                    signal_key=f"usage_spike:{conv_ref}",
                    signal_kind="usage_spike",
                    title=title,
                    why_it_matters="单次调用 token 用量超过 50 万，远超常规水平，可能存在循环调用、巨大文件摄入或失控进程，需要确认是否符合预期。",
                    severity="medium",
                    confidence="high",
                    priority_score=70,
                    facts=spike_conv_facts if spike_conv_facts else [dict(r) for r in group],
                    affected_scope={
                        "conversation_count": 1 if conv_ref != "global" else len(signals_by_conv),
                        "max_single_call_tokens": max_total,
                        "spike_call_count": len(group),
                        "input_tokens": int(max_row["input_tokens"] or 0),
                        "output_tokens": int(max_row["output_tokens"] or 0),
                        "conversation_ref": conv_ref if conv_ref != "global" else None,
                    },
                    evidence_groups=[
                        _object_group(conn, "conversation", f"用量突增 {conv_ref}", spike_conv_facts)
                        if spike_conv_facts else [],
                    ],
                    suggested_actions=[
                        f"检查会话 {conv_ref} 的调用详情，确认是否有循环调用或巨大文件摄入。",
                    ],
                    reason=reason,
                )
            )

    # --- low_cache_hit_rate: input_tokens > 10,000 AND cache_hit_rate < 10% ---
    low_cache_rows = []
    for row in unused_usage_facts:
        inp = int(row["input_tokens"] or 0)
        cached = int(row["cached_input_tokens"] or 0)
        cache_obs = bool(row["cache_observed"])
        if inp > 10_000 and cache_obs and cached / inp < 0.10:
            low_cache_rows.append(row)

    if low_cache_rows:
        fact_ids = [r["fact_id"] for r in low_cache_rows]
        usage_rows = usage_facts_for_signals(conn, fact_ids)
        signals_by_session = defaultdict(list)
        for ur in usage_rows:
            sess = ur.get("session_ref") or ur.get("session_id") or "unknown"
            signals_by_session[sess].append(ur)

        for sess_ref, group in signals_by_session.items():
            total_inp = sum(int(u["input_tokens"] or 0) for u in group)
            total_cached = sum(int(u["cached_input_tokens"] or 0) for u in group)
            hit_rate = round(total_cached / total_inp, 4) if total_inp > 0 else 0
            title = f"缓存命中率过低：{hit_rate:.1%}（input={total_inp:,}, cached={total_cached:,}）"
            # Fetch full observed_facts rows for evidence groups
            lc_conv_facts = []
            for r in low_cache_rows:
                sr = r["session_ref"] or r["session_id"] or "unknown"
                if sr == sess_ref:
                    full = conn.execute("select * from observed_facts where fact_id = ?", (r["fact_id"],)).fetchone()
                    if full:
                        lc_conv_facts.append(dict(full))
            results.append(
                upsert_signal(
                    conn,
                    signal_key=f"low_cache_hit_rate:{sess_ref}",
                    signal_kind="low_cache_hit_rate",
                    title=title,
                    why_it_matters="大输入量场景下缓存命中率低于 10%，说明缓存策略未生效或输入内容变化过大，导致重复计算成本高。",
                    severity="medium",
                    confidence="high",
                    priority_score=65,
                    facts=lc_conv_facts if lc_conv_facts else [dict(r) for r in low_cache_rows],
                    affected_scope={
                        "session_count": 1,
                        "total_input_tokens": total_inp,
                        "cached_input_tokens": total_cached,
                        "cache_hit_rate": hit_rate,
                        "fact_count": len(group),
                        "session_ref": sess_ref,
                    },
                    evidence_groups=[
                        _object_group(conn, "session", f"低缓存命中会话 {sess_ref}", lc_conv_facts)
                        if lc_conv_facts else [],
                    ],
                    suggested_actions=[
                        f"检查会话 {sess_ref} 的输入内容是否频繁变化；考虑启用更细粒度的缓存策略。",
                    ],
                    reason=reason,
                )
            )

    # --- unknown_usage_dominant: within 1-hour sliding window, unknown activity_tag > 50% ---
    # 滑动窗口语义：以 now 为右端点，取 (now-1h, now] 内每个 account 的全部事件，
    # 统一计算 unknown 占比。避免固定小时桶在小时边界处把同账号事件切分到不同桶
    # 导致占比计算失真（跨边界时会误触发多个信号）。
    hour_ago = now - timedelta(hours=1)

    # Group by account_ref within the 1-hour sliding window
    account_groups: dict[str, list[dict]] = defaultdict(list)
    for row in unused_usage_facts:
        try:
            occ = datetime.fromisoformat(row["occurred_at"])
            if occ.tzinfo is None:
                occ = occ.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if occ < hour_ago:
            continue
        account = row["account_ref"] or "unknown-account"
        account_groups[account].append(dict(row))

    for account, group in account_groups.items():
        total = len(group)
        unknown_count = sum(1 for f in group if f.get("activity_tag") == "unknown")
        if total > 0 and unknown_count / total > 0.50:
            fact_ids = [f["fact_id"] for f in group]
            usage_rows = usage_facts_for_signals(conn, fact_ids)
            title = f"未知用量主导：1 小时内 {unknown_count}/{total} 条 activity_tag=unknown"
            # Fetch full observed_facts rows for evidence groups
            unk_facts = []
            for f in group:
                full = conn.execute("select * from observed_facts where fact_id = ?", (f["fact_id"],)).fetchone()
                if full:
                    unk_facts.append(dict(full))
            # 计算滑动窗口内事件的时间范围，作为 affected_scope 的时序证据
            window_times: list[datetime] = []
            for f in group:
                try:
                    t = datetime.fromisoformat(f["occurred_at"])
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    window_times.append(t)
                except (ValueError, TypeError):
                    continue
            window_earliest = min(window_times).isoformat() if window_times else None
            window_latest = max(window_times).isoformat() if window_times else None
            results.append(
                upsert_signal(
                    conn,
                    signal_key=f"unknown_usage_dominant:{account}",
                    signal_kind="unknown_usage_dominant",
                    title=title,
                    why_it_matters="短时间内大量用量记录的 activity_tag 为 unknown，说明采集端未能正确标记用途，影响成本归因和分析。",
                    severity="low",
                    confidence="high",
                    priority_score=60,
                    facts=unk_facts if unk_facts else [dict(r) for r in unused_usage_facts],
                    affected_scope={
                        "account_ref": account,
                        "window_earliest_at": window_earliest,
                        "window_latest_at": window_latest,
                        "total_facts": total,
                        "unknown_count": unknown_count,
                        "unknown_ratio": round(unknown_count / total, 4),
                    },
                    evidence_groups=[
                        _object_group(conn, "account", f"账号 {account} 1 小时窗口", unk_facts)
                        if unk_facts else [],
                    ],
                    suggested_actions=[
                        f"检查账号 {account} 的采集端配置，确认 activity_tag 是否正确标记。",
                    ],
                    reason=reason,
                )
            )

    return results


def _make_loop_stuck_signal(
    conn: sqlite3.Connection,
    upsert_signal,
    conv_ref: str,
    tool_events: list[sqlite3.Row],
    reason: str,
    span: timedelta,
) -> dict:
    """Build an agent_loop_stuck signal from detected tool events."""
    # Gather projections for context
    projection_map = _primary_projections_by_fact_id(conn, [te["fact_id"] for te in tool_events])
    projections = [projection_map.get(te["fact_id"], {}) for te in tool_events]

    tool_names = set()
    for p in projections:
        tn = p.get("tool_name") or p.get("tool") or p.get("name")
        if tn:
            tool_names.add(str(tn))

    fact_ids = [te["fact_id"] for te in tool_events]
    facts = conn.execute(
        "select * from observed_facts where fact_id in ({}) order by occurred_at, fact_id".format(
            ",".join("?" for _ in fact_ids)
        ),
        fact_ids,
    ).fetchall()

    if not facts:
        facts = tool_events

    title = f"Agent 卡循环：{len(tool_events):,} 次工具调用无产出（{span.total_seconds()/60:.0f} 分钟）"
    return upsert_signal(
        conn,
        signal_key=f"agent_loop_stuck:{conv_ref}",
        signal_kind="agent_loop_stuck",
        title=title,
        why_it_matters="Agent 在一段时间内反复调用工具但没有产生新的内容输出，可能陷入无效循环，浪费资源且无法推进任务。",
        severity="high",
        confidence="high",
        priority_score=75,
        facts=facts,
        affected_scope={
            "conversation_count": 1,
            "tool_call_count": len(tool_events),
            "window_minutes": LOOP_STUCK_WINDOW_MINUTES,
            "tool_names": sorted(tool_names) or ["unknown"],
            "conversation_ref": conv_ref,
        },
        evidence_groups=[
            _object_group(conn, "conversation", f"卡循环会话 {conv_ref}", facts),
        ],
        suggested_actions=[
            f"打开会话 {conv_ref}，检查最近的工具调用链是否陷入无效循环；考虑设置最大重试次数。",
        ],
        reason=reason,
    )



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



