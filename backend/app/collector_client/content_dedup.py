from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from app.collector_client.content_events import content_identity
from app.collector_client.telemetry_utils import hash_value


def stamp_content_identity(fact: dict, path: Path, record: dict) -> None:
    identity = content_identity(record)
    content_text = " ".join(identity["content_text"].split())
    if not content_text:
        return
    digest = hash_value(
        "content-semantic-v1",
        path.as_posix(),
        identity["role"],
        hash_value(content_text),
        _time_bucket(str(fact.get("occurred_at") or "")),
    )
    fact["source_event_id"] = f"codex-content-{digest[:20]}"
    fact["span"] = f"codex-content:{digest[:12]}"
    fact["source_specific"]["semantic_content_key"] = digest
    fact["source_specific"]["dedupe_strategy"] = "content_semantic_v1"


def add_or_merge_content_fact(facts: list[dict], content_index: dict[str, int], fact: dict) -> None:
    semantic_key = fact.get("source_specific", {}).get("semantic_content_key")
    if fact.get("fact_type") != "content" or not semantic_key:
        facts.append(fact)
        return
    if semantic_key not in content_index:
        content_index[semantic_key] = len(facts)
        facts.append(fact)
        return
    index = content_index[semantic_key]
    facts[index] = _merge_content_facts(facts[index], fact)


def _merge_content_facts(existing: dict, incoming: dict) -> dict:
    preferred, other = (incoming, existing) if _event_priority(incoming) > _event_priority(existing) else (existing, incoming)
    merged = deepcopy(preferred)
    merged["source_refs"] = _merged_source_refs(preferred, other)
    source_specific = dict(preferred.get("source_specific", {}))
    source_specific["collapsed_event_types"] = sorted(_event_types(existing) | _event_types(incoming))
    merged["source_specific"] = source_specific
    return merged


def _merged_source_refs(preferred: dict, other: dict) -> dict:
    refs = dict(preferred.get("source_refs", {}))
    primary = str(refs.get("source_key") or "")
    keys = _source_keys(preferred) + _source_keys(other)
    alternates = sorted(key for key in dict.fromkeys(keys) if key and key != primary)
    if alternates:
        refs["alternate_source_keys"] = alternates
    refs["collapsed_source_count"] = len(alternates) + (1 if primary else 0)
    return refs


def _source_keys(fact: dict) -> list[str]:
    refs = fact.get("source_refs", {})
    if not isinstance(refs, dict):
        return []
    keys = [str(refs.get("source_key") or "")]
    alternates = refs.get("alternate_source_keys")
    if isinstance(alternates, list):
        keys.extend(str(item) for item in alternates)
    return [key for key in keys if key]


def _event_types(fact: dict) -> set[str]:
    source_specific = fact.get("source_specific", {})
    if not isinstance(source_specific, dict):
        return set()
    values = set()
    if source_specific.get("codex_event_type"):
        values.add(str(source_specific["codex_event_type"]))
    collapsed = source_specific.get("collapsed_event_types")
    if isinstance(collapsed, list):
        values.update(str(item) for item in collapsed)
    return values


def _event_priority(fact: dict) -> int:
    event_types = _event_types(fact)
    if "response_item:message" in event_types:
        return 3
    if event_types & {"event_msg:agent_message", "event_msg:user_message"}:
        return 2
    return 1


def _time_bucket(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:19]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat()
