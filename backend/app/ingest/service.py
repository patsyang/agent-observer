from __future__ import annotations

import json
import sqlite3
import hashlib
from datetime import UTC, datetime

from app.behavior_signals.helpers import canonical_signature, exit_code_from_summary
from app.collector_client.version import COLLECTOR_PROTOCOL_VERSION
from app.conversations.materialize import (
    FactProjection,
    apply as materialize_apply,
    refresh as materialize_refresh,
)
from app.evidence.presentation import projection_preview, raw_available, raw_status_label
from app.processing.jobs import JOB_TYPE_SIGNAL_UPDATE, enqueue_processing_job
from app.sensitive import detect_for_fact, object_type_from_matches


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json(value: dict | None) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"))


def ingest_telemetry(conn: sqlite3.Connection, batch: dict) -> dict:
    _validate_batch_protocol(batch)
    batch_id = batch["batch_id"]
    collector_id = batch["collector_id"]
    source_meta = _batch_source_meta(batch)
    source_id = source_meta["source_id"]
    source = source_meta["source"]
    agent_type = source_meta["agent_type"]
    source_kind = source_meta["source_kind"]
    cursor = batch.get("cursor", "")
    accepted = 0
    duplicates = 0
    pending_jobs: dict[str, dict] = {}
    now = _now()

    for item in batch.get("items", []):
        _validate_required_raw_content(item)
        source_event_id = item["source_event_id"]
        sensitive_matches, sensitive_object_type = _detect_fact_sensitive(item)
        if sensitive_matches:
            _stamp_sensitive_into_item(item, sensitive_matches)
        existing = conn.execute(
            "select fact_id from observed_facts where collector_id = ? and source_id = ? and source_event_id = ?",
            (collector_id, source_id, source_event_id),
        ).fetchone()
        if existing:
            _enrich_existing_raw_projection(conn, existing["fact_id"], item)
            if sensitive_matches:
                _write_sensitive_risk(conn, existing["fact_id"], sensitive_object_type, pending_jobs)
            _materialize_fact(
                conn,
                fact_id=existing["fact_id"],
                item=item,
                sensitive_matches=sensitive_matches,
                preview=_list_projection_preview(item),
                agent_type=agent_type,
                source_id=source_id,
                source_kind=source_kind,
                dedup=True,
            )
            duplicates += 1
            continue
        fact_id = _fact_id(conn, collector_id, source_id, source_event_id)
        preview = _list_projection_preview(item)
        refs = item.get("source_refs") or {}
        specific = item.get("source_specific") or {}
        normalized_event_type = _normalized_event_type(item)
        conn.execute(
            """
            insert into observed_facts (
              fact_id, source_event_id, batch_id, collector_id, source_id, source, agent_type, source_kind,
              fact_type, category, normalized_event_type, quality,
              severity, summary, occurred_at, promoted_to_signal, source_refs_json,
              source_specific_json, content_preview, raw_available, raw_status, conversation_ref,
              session_ref, source_event_type, source_path_hash, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                source_event_id,
                batch_id,
                collector_id,
                source_id,
                source,
                agent_type,
                source_kind,
                item.get("fact_type", "unknown"),
                item.get("category", "uncategorized"),
                normalized_event_type,
                item.get("quality", "low"),
                item.get("severity", "low"),
                item["summary"],
                item["occurred_at"],
                _json(refs),
                _json(specific),
                preview["content_preview"],
                1 if preview["raw_available"] else 0,
                preview["raw_status"],
                str(refs.get("conversation_ref") or ""),
                str(refs.get("session_ref") or ""),
                normalized_event_type,
                str(refs.get("source_path_hash") or ""),
                now,
            ),
        )
        _insert_evidence_projections(conn, fact_id, item)
        if sensitive_matches:
            _write_sensitive_risk(conn, fact_id, sensitive_object_type, pending_jobs)
        _insert_optional_signals(conn, fact_id, item)
        _materialize_fact(
            conn,
            fact_id=fact_id,
            item=item,
            sensitive_matches=sensitive_matches,
            preview=preview,
            agent_type=agent_type,
            source_id=source_id,
            source_kind=source_kind,
        )
        accepted += 1
        for job in _signal_jobs_for_item(item, source):
            pending_jobs[job["job_id"]] = job

    conn.execute(
        """
        insert or replace into telemetry_batches (
          batch_id, collector_id, source_id, source, agent_type, source_kind, protocol_version, agent_version,
          cursor, accepted_count, duplicate_count, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            collector_id,
            source_id,
            source,
            agent_type,
            source_kind,
            batch["protocol_version"],
            batch["agent_version"],
            cursor,
            accepted,
            duplicates,
            now,
        ),
    )
    for job in pending_jobs.values():
        enqueue_processing_job(
            conn,
            job_type=job["job_type"],
            scope_type=job["scope_type"],
            scope_id=job["scope_id"],
            priority=job["priority"],
        )
    conn.commit()
    job_ids = sorted(pending_jobs)
    return {
        "batch_id": batch_id,
        "accepted": accepted,
        "duplicates": duplicates,
        "processing_jobs_queued": len(job_ids),
        "processing_job_ids": job_ids,
    }


def _materialize_fact(
    conn: sqlite3.Connection,
    *,
    fact_id: str,
    item: dict,
    sensitive_matches: list,
    preview: dict,
    agent_type: str,
    source_id: str,
    source_kind: str,
    dedup: bool = False,
) -> None:
    """把这条 fact 投射进会话物化层（与 ingest 同事务，不 commit）。

    单条失败不波及 ingest 事务（仿 _detect_fact_sensitive 的约定）；遗漏可由
    ``scripts.rebuild_conversations`` 补齐。
    """
    try:
        projection = FactProjection.from_item(
            conn,
            fact_id=fact_id,
            item=item,
            sensitive_matches=sensitive_matches,
            preview=preview,
            agent_type=agent_type,
            source_id=source_id,
            source_kind=source_kind,
        )
        if dedup:
            materialize_refresh(conn, fact_id, projection)
        else:
            materialize_apply(conn, projection)
    except Exception:
        pass


def _validate_batch_protocol(batch: dict) -> None:
    if batch.get("protocol_version") != COLLECTOR_PROTOCOL_VERSION:
        raise ValueError("unsupported_collector_protocol")
    if not str(batch.get("agent_version") or "").strip():
        raise ValueError("agent_version_required")


def _batch_source_meta(batch: dict) -> dict[str, str]:
    source_id = str(batch.get("source_id") or "").strip()
    agent_type = str(batch.get("agent_type") or "").strip()
    source_kind = str(batch.get("source_kind") or "").strip()
    if not source_id or not agent_type or not source_kind:
        raise ValueError("source_metadata_required")
    return {
        "source_id": source_id,
        "source": str(batch.get("source") or agent_type),
        "agent_type": agent_type,
        "source_kind": source_kind,
    }


def _validate_required_raw_content(item: dict) -> None:
    if item.get("fact_type") == "content" or item.get("category") in {
        "agent_prompt",
        "agent_response",
        "agent_reasoning",
    }:
        if not _has_raw_content(item):
            raise ValueError("raw_content_required")


def _enrich_existing_raw_projection(conn: sqlite3.Connection, fact_id: str, item: dict) -> None:
    if not _has_raw_content(item):
        return
    preview = _list_projection_preview(item)
    conn.execute(
        """
        update observed_facts
        set summary = ?, quality = ?, severity = ?, source_refs_json = ?, source_specific_json = ?,
            content_preview = ?, raw_available = ?, raw_status = ?,
            conversation_ref = ?, session_ref = ?, source_event_type = ?, source_path_hash = ?
        where fact_id = ?
        """,
        (
            item["summary"],
            item.get("quality", "low"),
            item.get("severity", "low"),
            _json(item.get("source_refs")),
            _json(item.get("source_specific")),
            preview["content_preview"],
            1 if preview["raw_available"] else 0,
            preview["raw_status"],
            str((item.get("source_refs") or {}).get("conversation_ref") or ""),
            str((item.get("source_refs") or {}).get("session_ref") or ""),
            _normalized_event_type(item),
            str((item.get("source_refs") or {}).get("source_path_hash") or ""),
            fact_id,
        ),
    )
    for projection in _normalized_projections(item):
        raw_content = _raw_content(projection, item)
        if raw_content is None:
            continue
        row = _matching_projection(conn, fact_id, projection, item)
        if row is None:
            continue
        conn.execute(
            """
            update evidence_projections
            set projection_json = ?, upload_raw = 1, raw_content = ?
            where projection_id = ?
            """,
            (
                _json(projection.get("projection") or projection.get("projection_json") or item.get("projection")),
                raw_content,
                row["projection_id"],
            ),
        )


def _matching_projection(conn: sqlite3.Connection, fact_id: str, projection: dict, item: dict) -> sqlite3.Row | None:
    category = projection.get("category", item.get("category", "uncategorized"))
    span = projection.get("span", item.get("span", ""))
    raw_hash = projection.get("raw_hash", item["raw_hash"])
    row = conn.execute(
        """
        select projection_id from evidence_projections
        where fact_id = ? and raw_hash = ? and category = ? and span = ?
        order by projection_id
        limit 1
        """,
        (fact_id, raw_hash, category, span),
    ).fetchone()
    if row is not None:
        return row
    row = conn.execute(
        """
        select projection_id from evidence_projections
        where fact_id = ? and raw_hash = ?
        order by projection_id
        limit 1
        """,
        (fact_id, raw_hash),
    ).fetchone()
    if row is not None:
        return row
    rows = conn.execute(
        "select projection_id from evidence_projections where fact_id = ? order by projection_id limit 2",
        (fact_id,),
    ).fetchall()
    return rows[0] if len(rows) == 1 else None


def _has_raw_content(item: dict) -> bool:
    return any(_raw_content(projection, item) is not None for projection in _normalized_projections(item))


def _fact_id(conn: sqlite3.Connection, collector_id: str, source_id: str, source_event_id: str) -> str:
    if conn.execute("select 1 from observed_facts where fact_id = ?", (source_event_id,)).fetchone() is None:
        return source_event_id
    suffix = hashlib.sha256(f"{collector_id}:{source_id}:{source_event_id}".encode("utf-8")).hexdigest()[:20]
    return f"{collector_id}-{suffix}"


def _normalized_event_type(item: dict) -> str:
    specific = item.get("source_specific") or {}
    return str(
        item.get("normalized_event_type")
        or specific.get("event_type")
        or specific.get("codex_event_type")
        or specific.get("workbuddy_event_type")
        or ""
    )


def _insert_evidence_projections(conn: sqlite3.Connection, fact_id: str, item: dict) -> None:
    for index, projection in enumerate(_normalized_projections(item, fact_id)):
        projection_id = _projection_id(conn, fact_id, projection.get("projection_id") or f"proj-{fact_id}-{index + 1}")
        conn.execute(
            """
            insert into evidence_projections (
              projection_id, fact_id, category, span, raw_hash, projection_json, upload_raw, raw_content
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                projection_id,
                fact_id,
                projection.get("category", item.get("category", "uncategorized")),
                projection.get("span", item.get("span", "")),
                projection.get("raw_hash", item["raw_hash"]),
                _json(projection.get("projection") or projection.get("projection_json") or item.get("projection")),
                1 if bool(projection.get("upload_raw", item.get("upload_raw", False))) else 0,
                _raw_content(projection, item),
            ),
        )


def _normalized_projections(item: dict, fact_id: str | None = None) -> list[dict]:
    default_projection_id = f"proj-{fact_id}" if fact_id else ""
    if item.get("evidence_projections"):
        return item["evidence_projections"]
    projection_value = item.get("projection")
    projection = {
        "projection_id": default_projection_id,
        "category": item.get("category", "uncategorized"),
        "span": item.get("span", ""),
        "raw_hash": item["raw_hash"],
        "projection": projection_value,
    }
    if isinstance(projection_value, dict):
        if "upload_raw" in projection_value:
            projection["upload_raw"] = projection_value["upload_raw"]
        if "raw_content" in projection_value:
            projection["raw_content"] = projection_value["raw_content"]
    return [projection]


def _projection_id(conn: sqlite3.Connection, fact_id: str, projection_id: str) -> str:
    if conn.execute("select 1 from evidence_projections where projection_id = ?", (projection_id,)).fetchone() is None:
        return projection_id
    suffix = hashlib.sha256(f"{fact_id}:{projection_id}".encode("utf-8")).hexdigest()[:12]
    return f"proj-{fact_id}-{suffix}"


def _raw_content(projection: dict, item: dict) -> str | None:
    value = projection.get("raw_content", item.get("raw_content"))
    if value is None:
        return None
    return str(value)


def _list_projection_preview(item: dict) -> dict:
    projection = _normalized_projections(item)[0]
    projection_json = projection.get("projection") or projection.get("projection_json") or item.get("projection") or {}
    raw_content = _raw_content(projection, item)
    upload_raw = bool(projection.get("upload_raw", item.get("upload_raw", False)))
    category = projection.get("category", item.get("category", "uncategorized"))
    return {
        "content_preview": projection_preview(projection_json, raw_content, item.get("summary", ""), category),
        "raw_available": raw_available(upload_raw, raw_content),
        "raw_status": raw_status_label(upload_raw, raw_content),
    }


def _insert_optional_signals(conn: sqlite3.Connection, fact_id: str, item: dict) -> None:
    if error := item.get("error_signature"):
        signature_key = error["signature_key"]
        category = error.get("category", item.get("category", "error"))
        conn.execute(
            """
            insert into error_signatures (
              signature_key, fact_id, category, first_seen_at, last_seen_at, occurrences
            ) values (?, ?, ?, ?, ?, 1)
            on conflict(signature_key) do update set
              last_seen_at = excluded.last_seen_at,
              occurrences = error_signatures.occurrences + 1
            """,
            (
                signature_key,
                fact_id,
                category,
                item["occurred_at"],
                item["occurred_at"],
            ),
        )
        conn.execute(
            """
            insert or ignore into error_signature_facts (
              signature_key, fact_id, category, occurred_at
            ) values (?, ?, ?, ?)
            """,
            (signature_key, fact_id, category, item["occurred_at"]),
        )
    if usage := item.get("usage"):
        conn.execute(
            """
            insert into usage_signals (
              signal_id, fact_id, scope, units, activity_tag,
              session_id, conversation_id, project_ref, account_ref,
              input_tokens, output_tokens, total_tokens, cached_input_tokens,
              cache_write_input_tokens, reasoning_output_tokens, model, provider,
              credit, unit_basis, observability_level, cache_observed
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"usage-{fact_id}",
                fact_id,
                usage.get("scope", "unknown"),
                int(usage.get("units", 0)),
                usage.get("activity_tag", "unknown"),
                usage.get("session_id", "unknown"),
                usage.get("conversation_id", "unknown"),
                usage.get("project_ref", "unknown"),
                usage.get("account_ref", "unknown"),
                int(usage.get("input_tokens", 0)),
                int(usage.get("output_tokens", 0)),
                int(usage.get("total_tokens", 0)),
                int(usage.get("cached_input_tokens", 0)),
                int(usage.get("cache_write_input_tokens", 0)),
                int(usage.get("reasoning_output_tokens", 0)),
                str(usage.get("model") or ""),
                str(usage.get("provider") or ""),
                float(usage.get("credit", 0) or 0),
                str(usage.get("unit_basis") or "non_cached_input_plus_output"),
                str(usage.get("observability_level") or "total_only"),
                1 if bool(usage.get("cache_observed")) else 0,
            ),
        )
    if risk := item.get("risk"):
        conn.execute(
            """
            insert into risk_signals (signal_id, fact_id, risk_type, severity, object_type)
            values (?, ?, ?, ?, ?)
            """,
            (
                f"risk-{fact_id}",
                fact_id,
                risk.get("risk_type", "unknown"),
                risk.get("severity", item.get("severity", "low")),
                risk.get("object_type", "unknown"),
            ),
        )


def _signal_jobs_for_item(item: dict, source: str) -> list[dict]:
    jobs: list[dict] = []
    category = str(item.get("category") or "")
    if error := item.get("error_signature"):
        error_category = str(error.get("category") or category)
        if error_category in {"tool_execution_failure", "workflow_step_failure"}:
            jobs.append(_job("execution", canonical_signature(str(error["signature_key"])), 80))
    if category in {"tool_execution_timeout", "workflow_step_timeout"}:
        jobs.append(_job("timeout", _timeout_scope_key(item, source), 80))
    risk = item.get("risk") if isinstance(item.get("risk"), dict) else {}
    risk_type = str(risk.get("risk_type") or category)
    if risk_type == "file_change":
        conversation_ref = str((item.get("source_refs") or {}).get("conversation_ref") or "")
        if conversation_ref:
            jobs.append(_job("file_change", conversation_ref, 80))
    if risk_type == "destructive_operation":
        conversation_ref = str((item.get("source_refs") or {}).get("conversation_ref") or "")
        if conversation_ref:
            jobs.append(_job("risk", f"destructive_operation:{conversation_ref}", 90))
    if risk_type == "sensitive_content_exposure":
        conversation_ref = str((item.get("source_refs") or {}).get("conversation_ref") or "")
        if conversation_ref:
            jobs.append(_job("risk", f"sensitive_content_exposure:{conversation_ref}", 95))
    return jobs


def _job(scope_type: str, scope_id: str, priority: int) -> dict:
    return {
        "job_id": f"{JOB_TYPE_SIGNAL_UPDATE}:{scope_type}:{scope_id}",
        "job_type": JOB_TYPE_SIGNAL_UPDATE,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "priority": priority,
    }


# ---------------------------------------------------------------------------
# 敏感内容检测接入（L2 detector — sensitive risk_signal 的唯一写者）
#
# collector 不再做敏感检测，ingest 在写 projection 前算好 sensitive_matches 一次写齐
# （零 read-back），命中即写 risk_signals（object_type 派生索引）+ 入队聚合 job。
# detector 内部吞异常 [F6]、raw_content 截断，单条 fact 失败不波及事务。
# ---------------------------------------------------------------------------

_SENSITIVE_JOB_SCOPE = "sensitive_content_exposure"


def _detect_fact_sensitive(item: dict) -> tuple[list[dict], str | None]:
    """对 content/tool fact 跑 detector，返回 (high_matches, object_type)；无命中返回 ([], None)。

    [F6] 整个函数体包 try/except，单条 fact 的任何异常（KeyError 等）都不波及 ingest 事务。
    """
    if item.get("fact_type") not in {"content", "tool"}:
        return [], None
    try:
        # 优先只扫 raw_content（完整 record，含 content_text / command / args，最全）；缺失才扫
        # projection_json —— 避免两者重叠导致同一 PII 被重复命中（raw_content 是 projection 的超集）。
        raw_parts: list[str] = []
        projection_parts: list[str] = []
        for projection in _normalized_projections(item):
            raw_content = _raw_content(projection, item)
            if raw_content:
                raw_parts.append(raw_content)
            else:
                projection_value = projection.get("projection") or projection.get("projection_json") or item.get("projection")
                if projection_value:
                    projection_parts.append(json.dumps(projection_value, ensure_ascii=False, sort_keys=True, default=str))
        text = "\n".join(raw_parts) if raw_parts else "\n".join(projection_parts)
        high = detect_for_fact(text, None, source="ingest")
        if not high:
            return [], None
        return high, object_type_from_matches(high)
    except Exception:
        return [], None


def _primary_projection_dict(item: dict) -> dict | None:
    """取 item 的主 projection dict（用于注入 sensitive_matches）。"""
    if item.get("evidence_projections"):
        proj0 = item["evidence_projections"][0]
        if not isinstance(proj0.get("projection"), dict):
            proj0["projection"] = {}
        return proj0["projection"]
    projection = item.get("projection")
    if not isinstance(projection, dict):
        item["projection"] = {}
        projection = item["projection"]
    return projection


def _stamp_sensitive_into_item(item: dict, matches: list[dict]) -> None:
    """把 sensitive_matches 注入 item 主 projection dict，使后续 INSERT/UPDATE 一次写齐。

    真值检测 [F1]：空 list 也视为"无"，避免 collector 写过的空 sensitive_matches 守卫失效。
    """
    target = _primary_projection_dict(item)
    if target is None:
        return
    if not target.get("sensitive_matches"):
        target["sensitive_matches"] = matches
        target["sensitivity_confidence"] = "high"
        target["sensitive_categories"] = sorted({m["category"] for m in matches})


def _enqueue_sensitive_job(pending_jobs: dict[str, dict], conversation_ref: str) -> None:
    """按会话(conversation_ref)入队敏感信号处理 job（配合按任务聚合）。"""
    job_id = f"{JOB_TYPE_SIGNAL_UPDATE}:risk:{_SENSITIVE_JOB_SCOPE}:{conversation_ref}"
    pending_jobs[job_id] = {
        "job_id": job_id,
        "job_type": JOB_TYPE_SIGNAL_UPDATE,
        "scope_type": "risk",
        "scope_id": f"{_SENSITIVE_JOB_SCOPE}:{conversation_ref}",
        "priority": 95,
    }


def _write_sensitive_risk(conn: sqlite3.Connection, fact_id: str, object_type: str, pending_jobs: dict[str, dict]) -> None:
    """UPSERT sensitive risk_signal + 按会话入队信号处理 job。"""
    conn.execute(
        "insert into risk_signals (signal_id, fact_id, risk_type, severity, object_type) "
        "values (?, ?, 'sensitive_content_exposure', 'high', ?) "
        "on conflict(signal_id) do update set object_type=excluded.object_type, severity='high'",
        (f"risk:sensitive:{fact_id}", fact_id, object_type),
    )
    row = conn.execute("select conversation_ref from observed_facts where fact_id = ?", (fact_id,)).fetchone()
    conversation_ref = row["conversation_ref"] if row else ""
    if conversation_ref:
        _enqueue_sensitive_job(pending_jobs, conversation_ref)


def _timeout_scope_key(item: dict, source: str) -> str:
    projection = _normalized_projections(item)[0].get("projection") or item.get("projection") or {}
    refs = item.get("source_refs") or {}
    category = str(item.get("category") or "")
    if category == "workflow_step_timeout" and projection.get("workflow") and projection.get("run_id"):
        return f"workflow:{projection.get('workflow')}:{projection.get('run_id')}:{projection.get('command_fingerprint')}"
    agent_type = refs.get("agent_type") or source or "unknown-agent"
    workspace = refs.get("workspace_id") or refs.get("workspace_path") or "unknown-workspace"
    conversation = refs.get("conversation_ref") or refs.get("session_ref") or "unknown-conversation"
    tool = projection.get("tool_name") or projection.get("tool") or projection.get("name") or "tool"
    status = "timeout" if projection.get("is_timeout") else f"exit:{projection.get('exit_code') or exit_code_from_summary(str(item.get('summary') or '')) or 'unknown'}"
    workflow = projection.get("workflow") or ""
    run_id = projection.get("run_id") or ""
    if workflow and run_id:
        return f"{agent_type}:{workspace}:workflow:{workflow}:{run_id}:{tool}:{status}"
    return f"{agent_type}:{workspace}:{conversation}:{tool}:{status}"
