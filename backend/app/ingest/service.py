from __future__ import annotations

import json
import sqlite3
import hashlib
from datetime import UTC, datetime

from app.evidence.presentation import projection_preview, raw_available, raw_status_label


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json(value: dict | None) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"))


def ingest_telemetry(conn: sqlite3.Connection, batch: dict) -> dict:
    batch_id = batch["batch_id"]
    collector_id = batch["collector_id"]
    source = batch.get("source", "codex")
    cursor = batch.get("cursor", "")
    accepted = 0
    duplicates = 0
    affected_fact_ids: list[str] = []
    now = _now()

    for item in batch.get("items", []):
        source_event_id = item["source_event_id"]
        existing = conn.execute(
            "select fact_id from observed_facts where collector_id = ? and source_event_id = ?",
            (collector_id, source_event_id),
        ).fetchone()
        if existing:
            _enrich_existing_raw_projection(conn, existing["fact_id"], item)
            duplicates += 1
            continue
        fact_id = _fact_id(conn, collector_id, source_event_id)
        preview = _list_projection_preview(item)
        refs = item.get("source_refs") or {}
        specific = item.get("source_specific") or {}
        conn.execute(
            """
            insert into observed_facts (
              fact_id, source_event_id, batch_id, collector_id, source, fact_type, category, quality,
              severity, summary, occurred_at, promoted_to_story, source_refs_json,
              source_specific_json, content_preview, raw_available, raw_status, conversation_ref,
              session_ref, source_event_type, source_path_hash, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                source_event_id,
                batch_id,
                collector_id,
                source,
                item.get("fact_type", "unknown"),
                item.get("category", "uncategorized"),
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
                str(specific.get("codex_event_type") or ""),
                str(refs.get("source_path_hash") or ""),
                now,
            ),
        )
        _insert_evidence_projections(conn, fact_id, item)
        _insert_optional_signals(conn, fact_id, item)
        accepted += 1
        affected_fact_ids.append(fact_id)

    conn.execute(
        """
        insert or replace into telemetry_batches (
          batch_id, collector_id, source, cursor, accepted_count, duplicate_count, created_at
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (batch_id, collector_id, source, cursor, accepted, duplicates, now),
    )
    conn.commit()
    if affected_fact_ids:
        from app.stories.service import update_stories_for_facts

        update_stories_for_facts(conn, affected_fact_ids, reason="telemetry_ingest")
    return {"batch_id": batch_id, "accepted": accepted, "duplicates": duplicates}


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
            str((item.get("source_specific") or {}).get("codex_event_type") or ""),
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


def _fact_id(conn: sqlite3.Connection, collector_id: str, source_event_id: str) -> str:
    if conn.execute("select 1 from observed_facts where fact_id = ?", (source_event_id,)).fetchone() is None:
        return source_event_id
    suffix = hashlib.sha256(f"{collector_id}:{source_event_id}".encode("utf-8")).hexdigest()[:20]
    return f"{collector_id}-{suffix}"


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
                error["signature_key"],
                fact_id,
                error.get("category", item.get("category", "error")),
                item["occurred_at"],
                item["occurred_at"],
            ),
        )
    if usage := item.get("usage"):
        conn.execute(
            """
            insert into usage_signals (
              signal_id, fact_id, scope, units, activity_tag, usage_kind,
              session_id, conversation_id, project_ref, account_ref
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"usage-{fact_id}",
                fact_id,
                usage.get("scope", "unknown"),
                int(usage.get("units", 0)),
                usage.get("activity_tag", "unknown"),
                usage.get("usage_kind", "associated"),
                usage.get("session_id", "unknown"),
                usage.get("conversation_id", "unknown"),
                usage.get("project_ref", "unknown"),
                usage.get("account_ref", "unknown"),
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
