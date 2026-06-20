from __future__ import annotations

import json
import re
import sqlite3

from app.collector_client.command_context import command_error_projection
from app.stories.common import _loads, _snapshot_hash, _story_id, _window_cutoff
from app.stories.evidence import (
    _diagnostic_evidence_entries,
    _diagnostic_status_summary,
    _enrich_evidence_chain,
    _evidence_entries,
    _primary_projection,
    _usage_summary,
)
from app.stories.fact_stories import (
    build_risk_stories,
    build_risk_stories_for_facts,
    build_usage_stories,
    build_usage_stories_for_facts,
)
from app.stories.handling import handle_story, mark_story_read
from app.stories.presentation import (
    _attention_state,
    _error_conclusion,
    _impact_objects,
    _priority_score,
    _public_story,
    _recent_audit_summary,
    _row_to_story,
    _story_metadata,
)
from app.stories.repository import (
    _facts_by_ids,
    _related_facts,
    _remove_stale_command_timeout_stories,
    _remove_stale_error_stories,
    _remove_stale_risk_stories,
    _write_story_row,
)


def rebuild_stories(conn: sqlite3.Connection, reason: str = "manual") -> dict:
    stories = []
    command_timeout_stories = _build_command_timeout_stories(conn, reason)
    stories.extend(command_timeout_stories)
    error_story_ids: list[str] = []
    for signatures in _group_error_signatures(
        conn.execute("select * from error_signatures where category != 'command_timeout' order by signature_key").fetchall()
    ):
        if _is_command_timeout_signature(conn, signatures):
            continue
        story = _build_signature_story(conn, signatures, reason)
        if story:
            error_story_ids.append(story["story_id"])
        stories.append(story)
    stories.extend(build_usage_stories(conn, reason))
    risk_stories = build_risk_stories(conn, reason)
    stories.extend(risk_stories)
    _remove_stale_error_stories(conn, error_story_ids)
    _remove_stale_command_timeout_stories(conn, [story["story_id"] for story in command_timeout_stories if story])
    _remove_stale_risk_stories(conn, [story["story_id"] for story in risk_stories if story])
    conn.commit()
    return {"reason": reason, "updated": len([story for story in stories if story]), "stories": [story for story in stories if story]}


def update_stories_for_facts(conn: sqlite3.Connection, fact_ids: list[str], reason: str = "telemetry_ingest") -> dict:
    fact_ids = sorted({fact_id for fact_id in fact_ids if fact_id})
    if not fact_ids:
        return {"reason": reason, "updated": 0, "stories": []}
    facts = _facts_by_ids(conn, fact_ids)
    stories: list[dict] = []
    stories.extend(_build_command_timeout_stories_for_facts(conn, facts, reason))
    for signatures in _affected_error_signature_groups(conn, fact_ids):
        if not _is_command_timeout_signature(conn, signatures):
            stories.append(_build_signature_story(conn, signatures, reason))
    stories.extend(build_usage_stories_for_facts(conn, fact_ids, reason))
    stories.extend(build_risk_stories_for_facts(conn, fact_ids, reason))
    conn.commit()
    public_stories = [story for story in stories if story]
    return {"reason": reason, "updated": len(public_stories), "stories": public_stories}


def list_stories(
    conn: sqlite3.Connection,
    include_hidden: bool = False,
    window: str = "all",
    queue: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    current_page = max(1, int(page or 1))
    limit = max(1, min(int(page_size or 20), 100))
    offset = (current_page - 1) * limit
    clauses: list[str] = []
    params: list[str] = []
    if not include_hidden:
        clauses.append("attention_state in ('active', 'needs_review')")
    if queue == "actionable":
        clauses.append("story_key not like 'usage:%'")
    cutoff = _window_cutoff(window)
    if cutoff:
        clauses.append("coalesce(last_event_at, updated_at) >= ?")
        params.append(cutoff)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    total = conn.execute(f"select count(*) as total from observation_stories {where}", params).fetchone()["total"]
    rows = conn.execute(
        f"""
        select * from observation_stories
        {where}
        order by coalesce(last_event_at, updated_at) desc, priority_score desc, story_key
        limit ? offset ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return {
        "stories": [_row_to_story(conn, row, include_evidence_refs=False) for row in rows],
        "total": int(total),
        "page": current_page,
        "page_size": limit,
        "has_more": offset + len(rows) < int(total),
    }

def get_story_detail(conn: sqlite3.Connection, story_id: str) -> dict:
    row = conn.execute("select * from observation_stories where story_id = ?", (story_id,)).fetchone()
    if row is None:
        raise LookupError(story_id)
    story = _row_to_story(conn, row, include_evidence_refs=True)
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

def _build_command_timeout_stories(conn: sqlite3.Connection, reason: str) -> list[dict]:
    rows = conn.execute(
        """
        select of.*
        from observed_facts of
        where of.category in ('command_timeout', 'codex_error')
        order by of.occurred_at, of.fact_id
        """
    ).fetchall()
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        projection = _command_timeout_projection(conn, row["fact_id"])
        if not projection:
            continue
        workflow = str(projection.get("workflow") or "unknown")
        run_id = str(projection.get("run_id") or ("legacy-timeout" if workflow == "unknown" else "unknown"))
        groups.setdefault((workflow, run_id), []).append(row)
    stories = []
    for (workflow, run_id), facts in sorted(groups.items()):
        stories.append(_write_command_timeout_story(conn, workflow, run_id, facts, reason))
    return stories


def _build_command_timeout_stories_for_facts(conn: sqlite3.Connection, facts: list[sqlite3.Row], reason: str) -> list[dict]:
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for fact in facts:
        projection = _command_timeout_projection(conn, fact["fact_id"])
        if projection:
            key = (str(projection.get("workflow") or "unknown"), str(projection.get("run_id") or "unknown"))
            groups.setdefault(key, []).append(fact)
    stories = []
    for (workflow, run_id), fallback_facts in sorted(groups.items()):
        signature_rows = _command_timeout_signature_rows(conn, workflow, run_id)
        fact_ids = [row["fact_id"] for row in signature_rows]
        matching = _facts_by_ids(conn, fact_ids) if fact_ids else fallback_facts
        if matching:
            ordered = sorted(matching, key=lambda fact: (fact["occurred_at"], fact["fact_id"]))
            stories.append(_write_command_timeout_story(conn, workflow, run_id, ordered, reason))
    return stories


def _command_timeout_signature_rows(conn: sqlite3.Connection, workflow: str, run_id: str) -> list[sqlite3.Row]:
    prefix = f"command_timeout:{workflow}:{run_id}:"
    return conn.execute(
        """
        select *
        from error_signatures
        where category = 'command_timeout'
          and signature_key >= ?
          and signature_key < ?
        order by signature_key
        """,
        (prefix, f"{prefix}\uffff"),
    ).fetchall()


def _write_command_timeout_story(
    conn: sqlite3.Connection,
    workflow: str,
    run_id: str,
    facts: list[sqlite3.Row],
    reason: str,
) -> dict:
    story_key = f"command_timeout:{workflow}:{run_id}"
    story_id = _story_id(story_key)
    evidence_chain = []
    for fact in facts:
        evidence_chain.extend(_evidence_entries(conn, fact))
    latest_projection = _command_timeout_projection(conn, facts[-1]["fact_id"]) or _primary_projection(conn, facts[-1]["fact_id"])
    snapshot = {
        "reason": reason,
        "story_key": story_key,
        "evidence_chain": evidence_chain,
        "source_refs": [_loads(fact["source_refs_json"]) for fact in facts],
        "command_context": latest_projection,
    }
    snapshot_hash = _snapshot_hash(snapshot)
    existing = conn.execute("select snapshot_hash, attention_state from observation_stories where story_id = ?", (story_id,)).fetchone()
    handling = conn.execute("select * from story_handling_states where story_id = ?", (story_id,)).fetchone()
    duration = latest_projection.get("wall_time_seconds")
    duration_text = f"{float(duration):,.0f} 秒" if duration is not None else "未知时长"
    if workflow == "unknown":
        conclusion = f"检测到 {len(facts):,} 次命令超时，旧采集数据缺少命令输入，最近一次运行约 {duration_text}。"
        impact_objects = ["旧采集命令输出"]
        suggested_action = "重新下载并运行新版 collector，后续超时会关联命令、workflow 和 run_id。"
    else:
        conclusion = f"{workflow} resume 在 {run_id} 上运行约 {duration_text}后超时退出。"
        impact_objects = [run_id]
        suggested_action = "打开该 run 的 run.json 和 workflow-event.jsonl，定位超时卡点。"
    story = {
        "story_id": story_id,
        "story_key": story_key,
        "priority_score": 100,
        "evidence_refs": sorted(entry["evidence_ref"] for entry in evidence_chain),
        "usage_summary": _usage_summary(conn, [fact["fact_id"] for fact in facts]),
        "diagnostic_status_summary": _diagnostic_status_summary(conn, story_id),
        "attention_state": _attention_state(existing, handling, snapshot_hash),
        "current_snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "conclusion": conclusion,
        "impact_objects": impact_objects,
        "suggested_action": suggested_action,
    }
    story.update(_story_metadata(story_key, facts, evidence_chain))
    _write_story_row(conn, story)
    return _public_story(story, handling)

def _is_command_timeout_signature(conn: sqlite3.Connection, signatures: list[sqlite3.Row]) -> bool:
    if not signatures:
        return False
    for signature in signatures:
        if not _command_timeout_projection(conn, signature["fact_id"]):
            return False
    return True

def _command_timeout_projection(conn: sqlite3.Connection, fact_id: str) -> dict:
    projection = _primary_projection(conn, fact_id)
    if str(projection.get("exit_code")) == "124" or projection.get("error_kind") == "command_timeout":
        parsed = _command_timeout_from_raw(conn, fact_id)
        return {**projection, **parsed} if parsed else projection
    return {}

def _command_timeout_from_raw(conn: sqlite3.Connection, fact_id: str) -> dict:
    row = conn.execute(
        """
        select raw_content
        from evidence_projections
        where fact_id = ? and raw_content is not null
        order by projection_id
        limit 1
        """,
        (fact_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        record = json.loads(row["raw_content"])
    except json.JSONDecodeError:
        return {}
    projection = command_error_projection(record)
    if projection and projection.get("is_timeout"):
        return projection
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    output = str(payload.get("output") or "")
    exit_match = re.search(r"Exit code:\s*(-?\d+)", output)
    if not exit_match or exit_match.group(1) != "124":
        return {}
    wall_match = re.search(r"Wall time:\s*([0-9.]+)\s*seconds", output)
    timeout_match = re.search(r"timed out after\s*(\d+)\s*milliseconds", output, re.IGNORECASE)
    return {
        "exit_code": 124,
        "wall_time_seconds": float(wall_match.group(1)) if wall_match else None,
        "timeout_after_ms": int(timeout_match.group(1)) if timeout_match else None,
        "call_id": str(payload.get("call_id") or ""),
    }

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
    story.update(_story_metadata(story_key, facts, evidence_chain))
    story["latest_summary"] = ""
    _write_story_row(conn, story)
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


def _affected_error_signature_groups(conn: sqlite3.Connection, fact_ids: list[str]) -> list[list[sqlite3.Row]]:
    placeholders = ",".join("?" for _ in fact_ids)
    affected = conn.execute(
        f"select * from error_signatures where category != 'command_timeout' and fact_id in ({placeholders})",
        fact_ids,
    ).fetchall()
    if not affected:
        return []
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in affected:
        key = _canonical_signature_key(row["signature_key"])
        groups[key] = _signature_rows_for_canonical(conn, row["signature_key"])
    return [groups[key] for key in sorted(groups)]


def _signature_rows_for_canonical(conn: sqlite3.Connection, signature_key: str) -> list[sqlite3.Row]:
    parts = signature_key.split(":")
    if len(parts) >= 5 and re.fullmatch(r"[a-f0-9]{8}", parts[-1], re.IGNORECASE):
        prefix = ":".join(parts[:-1]) + ":"
        return conn.execute(
            """
            select *
            from error_signatures
            where category != 'command_timeout'
              and signature_key >= ?
              and signature_key < ?
            order by signature_key
            """,
            (prefix, f"{prefix}\uffff"),
        ).fetchall()
    return conn.execute(
        """
        select *
        from error_signatures
        where category != 'command_timeout' and signature_key = ?
        order by signature_key
        """,
        (signature_key,),
    ).fetchall()
