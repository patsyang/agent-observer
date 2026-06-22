from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter

from app.behavior_signals.common import dumps, loads, now_iso
from app.behavior_signals.evidence import enrichment_entries, evidence_entries
from app.collector_client.command_context import command_error_projection

KEY_PATH_PATTERNS = (
    (re.compile(r"(^|/)\.gitignore$", re.I), "项目忽略规则"),
    (re.compile(r"db/migrations?|migration", re.I), "数据库迁移"),
    (re.compile(r"collector|collector_client", re.I), "采集器实现"),
    (re.compile(r"workflow|commands?/", re.I), "工作流或命令入口"),
    (re.compile(r"policy|package|stack-contract|agentic\.lock", re.I), "策略或发布配置"),
)


def remove_stale(conn: sqlite3.Connection, active_ids: list[str]) -> None:
    if not active_ids:
        conn.execute("delete from behavior_signals")
        return
    placeholders = ",".join("?" for _ in active_ids)
    conn.execute(f"delete from behavior_signals where signal_id not in ({placeholders})", active_ids)


def canonical_signature(signature_key: str) -> str:
    parts = signature_key.split(":")
    if len(parts) >= 5 and re.fullmatch(r"[a-f0-9]{8}", parts[-1], re.IGNORECASE):
        return ":".join(parts[:-1] + [parts[1]])
    return signature_key


def signature_facts(conn: sqlite3.Connection, signatures: list[sqlite3.Row]) -> list[sqlite3.Row]:
    keys = [row["signature_key"] for row in signatures]
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"""
        select distinct of.*
        from error_signature_facts esf
        join observed_facts of on of.fact_id = esf.fact_id
        where esf.signature_key in ({placeholders})
        order by of.occurred_at, of.fact_id
        """,
        keys,
    ).fetchall()
    if rows:
        return rows
    return facts_by_ids(conn, [row["fact_id"] for row in signatures])


def facts_by_ids(conn: sqlite3.Connection, fact_ids: list[str]) -> list[sqlite3.Row]:
    if not fact_ids:
        return []
    placeholders = ",".join("?" for _ in fact_ids)
    return conn.execute(
        f"select * from observed_facts where fact_id in ({placeholders}) order by occurred_at, fact_id",
        fact_ids,
    ).fetchall()


def conversation_refs(facts: list[sqlite3.Row]) -> list[str]:
    return sorted({fact["conversation_ref"] for fact in facts if fact["conversation_ref"]})


def linked_conversations(facts: list[sqlite3.Row]) -> list[dict]:
    counts = Counter(fact["conversation_ref"] or "unknown" for fact in facts)
    last_seen: dict[str, str] = {}
    for fact in facts:
        ref = fact["conversation_ref"] or "unknown"
        last_seen[ref] = max(last_seen.get(ref, ""), fact["occurred_at"])
    return [
        {"conversation_ref": ref, "hit_count": count, "last_seen_at": last_seen.get(ref)}
        for ref, count in counts.most_common(10)
        if ref != "unknown"
    ]


def primary_projection(conn: sqlite3.Connection, fact_id: str) -> dict:
    row = conn.execute(
        "select projection_json from evidence_projections where fact_id = ? order by projection_id limit 1",
        (fact_id,),
    ).fetchone()
    return loads(row["projection_json"]) if row is not None else {}


def first_text(projections: list[dict], *keys: str) -> str:
    for projection in projections:
        for key in keys:
            value = projection.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def exit_code_from_summary(summary: str) -> str:
    match = re.search(r"exit[_ ]code[:= ]+(-?\d+)", summary, re.I)
    return match.group(1) if match else ""


def command_timeout_projection(conn: sqlite3.Connection, fact_id: str) -> dict:
    projection = primary_projection(conn, fact_id)
    if str(projection.get("exit_code")) == "124" or projection.get("error_kind") == "command_timeout":
        parsed = _command_timeout_from_raw(conn, fact_id)
        return {**projection, **parsed} if parsed else projection
    return {}


def risk_facts(conn: sqlite3.Connection, risk_type: str, object_type: str | None) -> list[sqlite3.Row]:
    params: list[str] = [risk_type]
    object_clause = ""
    if object_type:
        object_clause = "and rs.object_type = ?"
        params.append(object_type)
    return conn.execute(
        f"""
        select of.*
        from risk_signals rs
        join observed_facts of on of.fact_id = rs.fact_id
        where rs.risk_type = ? {object_clause}
        order by of.occurred_at, of.fact_id
        """,
        params,
    ).fetchall()


def path_hint(conn: sqlite3.Connection, fact: sqlite3.Row) -> str:
    rows = conn.execute(
        "select projection_json, raw_content from evidence_projections where fact_id = ? order by projection_id",
        (fact["fact_id"],),
    ).fetchall()
    for row in rows:
        projection = loads(row["projection_json"])
        for key in ("path", "file_path", "target", "workdir"):
            if projection.get(key):
                return str(projection[key]).replace("\\", "/")
        raw_path = _path_from_raw(row["raw_content"])
        if raw_path:
            return raw_path
    match = re.search(r"([A-Za-z0-9_.\-/]+(?:\.py|\.ts|\.tsx|\.json|\.md|\.sql|\.yaml|\.yml|\.toml|\.lock))", fact["summary"])
    return match.group(1).replace("\\", "/") if match else ""


def top_directories(paths: list[str]) -> list[str]:
    dirs = Counter("/".join(path.split("/")[:3]) if "/" in path else path for path in paths if path)
    return [path for path, _ in dirs.most_common(5)]


def key_path_label(path: str) -> str:
    if not path:
        return ""
    normalized = path.replace("\\", "/")
    for pattern, label in KEY_PATH_PATTERNS:
        if pattern.search(normalized):
            return label
    return ""


def high_confidence_sensitive(conn: sqlite3.Connection, fact_id: str) -> bool:
    rows = conn.execute(
        "select projection_json, raw_content from evidence_projections where fact_id = ?",
        (fact_id,),
    ).fetchall()
    for row in rows:
        projection = loads(row["projection_json"])
        if projection.get("sensitivity_confidence") == "high":
            return True
        matches = projection.get("sensitive_matches")
        if isinstance(matches, list) and any(isinstance(item, dict) and item.get("confidence") == "high" for item in matches):
            return True
    return False


def failure_group(conn: sqlite3.Connection, group_type: str, title: str, facts: list[sqlite3.Row], projections: list[dict]) -> dict:
    return {
        "group_id": f"{group_type}:{hashlib.sha256(title.encode('utf-8')).hexdigest()[:8]}",
        "group_type": group_type,
        "title": title,
        "summary": f"{len(facts):,} 条命中，最近 {facts[-1]['occurred_at'] if facts else '未知'}",
        "count": len(facts),
        "items": _items(conn, facts[:5], projections[:5]),
    }


def conversation_groups(conn: sqlite3.Connection, facts: list[sqlite3.Row], limit: int = 5) -> list[dict]:
    buckets: dict[str, list[sqlite3.Row]] = {}
    for fact in facts:
        buckets.setdefault(fact["conversation_ref"] or "unknown", []).append(fact)
    groups = []
    for ref, bucket in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0]))[:limit]:
        if ref == "unknown":
            continue
        groups.append(
            {
                "group_id": f"conversation:{ref}",
                "group_type": "conversation",
                "title": f"会话 {ref}",
                "summary": f"{len(bucket):,} 条命中",
                "count": len(bucket),
                "items": _items(conn, bucket[:5]),
            }
        )
    return groups


def object_group(conn: sqlite3.Connection, group_type: str, title: str, facts: list[sqlite3.Row]) -> dict:
    return {
        "group_id": f"{group_type}:{hashlib.sha256(title.encode('utf-8')).hexdigest()[:8]}",
        "group_type": group_type,
        "title": title,
        "summary": f"{len(facts):,} 条命中",
        "count": len(facts),
        "items": _items(conn, facts[:5]),
    }


def directory_group(paths: list[str]) -> dict:
    items = [{"summary": path, "content_preview": path, "occurred_at": None, "fact_id": None, "evidence_ref": path} for path in top_directories(paths)]
    return {"group_id": "object:top-directories", "group_type": "object", "title": "目录 Top", "summary": "修改最集中的目录", "count": len(items), "items": items}


def enrichment_group(conn: sqlite3.Connection, signal_id: str) -> dict:
    entries = enrichment_entries(conn, signal_id)
    return {
        "group_id": "failure:enrichment",
        "group_type": "failure",
        "title": "工具失败上下文补证",
        "summary": f"{len(entries):,} 条补证结果",
        "count": len(entries),
        "items": entries[:5],
    }


def normalize_note(note: str | None) -> str | None:
    value = " ".join((note or "").split()).strip()
    return value[:2000] if value else None


def write_audit(conn: sqlite3.Connection, signal_id: str, action: str, metadata: dict) -> None:
    now = now_iso()
    audit_id = hashlib.sha256(f"{signal_id}:{action}:{now}:{dumps(metadata)}".encode("utf-8")).hexdigest()[:24]
    conn.execute(
        """
        insert into audit_logs (audit_id, object_type, object_id, action, actor, metadata_json, created_at)
        values (?, 'behavior_signal', ?, ?, 'fixed-management-account', ?, ?)
        """,
        (audit_id, signal_id, action, dumps(metadata), now),
    )


def object_type_label(value: str) -> str:
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


def _items(conn: sqlite3.Connection, facts: list[sqlite3.Row], projections: list[dict] | None = None) -> list[dict]:
    items = []
    projections = projections or [{} for _ in facts]
    for fact, projection in zip(facts, projections):
        entries = evidence_entries(conn, fact)
        entry = entries[0] if entries else {}
        items.append(
            {
                "fact_id": fact["fact_id"],
                "evidence_ref": entry.get("evidence_ref", fact["fact_id"]),
                "occurred_at": fact["occurred_at"],
                "summary": fact["summary"],
                "conversation_ref": fact["conversation_ref"],
                "content_preview": entry.get("content_preview") or fact["content_preview"] or fact["summary"],
                "tool_name": projection.get("tool_name") or projection.get("tool") or projection.get("name"),
                "exit_code": projection.get("exit_code") or exit_code_from_summary(fact["summary"]),
            }
        )
    return items


def _command_timeout_from_raw(conn: sqlite3.Connection, fact_id: str) -> dict:
    row = conn.execute(
        "select raw_content from evidence_projections where fact_id = ? and raw_content is not null order by projection_id limit 1",
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
    return {"exit_code": 124, "wall_time_seconds": float(wall_match.group(1)) if wall_match else None}


def _path_from_raw(raw_content: str | None) -> str:
    if not raw_content:
        return ""
    try:
        record = json.loads(raw_content)
    except json.JSONDecodeError:
        return ""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    for source in (record, payload, args):
        for key in ("path", "target", "workdir", "file_path"):
            if source.get(key):
                return str(source[key]).replace("\\", "/")
    return ""
