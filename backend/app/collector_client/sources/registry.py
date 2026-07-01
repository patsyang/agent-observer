from __future__ import annotations

import time
from typing import Callable

from app.collector_client.config import CollectorConfig, SourceConfig
from app.collector_client.sources.base import SourceResult, source_payload
from app.collector_client.sources import claude as claude_source
from app.collector_client.sources import codex as codex_source
from app.collector_client.sources import workbuddy as workbuddy_source

SOURCE_COLLECTORS = {
    codex_source.SOURCE_KIND: codex_source.collect,
    workbuddy_source.SOURCE_KIND: workbuddy_source.collect,
    claude_source.SOURCE_KIND: claude_source.collect,
}


EmitEvent = Callable[[dict[str, object]], None]


def collect_sources(config: CollectorConfig, state: dict, sequence: int, emit: EmitEvent | None = None, cycle: int | None = None) -> list[SourceResult]:
    results: list[SourceResult] = []
    cursor_root = state.setdefault("cursor", {})
    source_cursors = cursor_root.setdefault("source_cursors", {})
    for source in config.sources:
        if not source.enabled:
            results.append(SourceResult(source, "offline", "disabled", []))
            continue
        source_cursor = source_cursors.setdefault(source.source_id, {})
        _emit_source(emit, "source_started", source, cycle)
        started_at = time.monotonic()
        try:
            result = _collect_source(config, source, source_cursor, sequence)
        except Exception:
            result = SourceResult(source, "degraded", "source_error", [])
        duration_ms = int((time.monotonic() - started_at) * 1000)
        _emit_source(emit, "source_completed", source, cycle, result=result, duration_ms=duration_ms)
        results.append(result)
    return results


def source_statuses(config: CollectorConfig, results: list[SourceResult] | None = None) -> list[dict]:
    by_id = {result.config.source_id: result for result in results or []}
    payloads = []
    for source in config.sources:
        result = by_id.get(source.source_id)
        if result is None:
            status = "online" if source.enabled and source.root.exists() else "source_missing"
            payloads.append(source_payload(source, status, status))
            continue
        payloads.append(source_payload(source, result.status, result.reason_code))
    return payloads


def _collect_source(config: CollectorConfig, source: SourceConfig, cursor: dict, sequence: int) -> SourceResult:
    kwargs = {
        "collector_id": config.collector_id,
        "sequence": sequence,
        "telemetry_mode": config.telemetry_mode,
        "history_window_days": config.history_window_days,
        "max_events": config.max_events_per_cycle,
        "cursor": cursor,
    }
    collector = SOURCE_COLLECTORS.get(source.source_kind)
    if collector:
        return collector(source, **kwargs)
    return SourceResult(source, "degraded", "unsupported_source_kind", [])


def _emit_source(
    emit: EmitEvent | None,
    mode: str,
    source: SourceConfig,
    cycle: int | None,
    *,
    result: SourceResult | None = None,
    duration_ms: int | None = None,
) -> None:
    if emit is None:
        return
    payload: dict[str, object] = {
        "status": "ok",
        "mode": mode,
        "cycle": cycle,
        "source_id": source.source_id,
        "agent_type": source.agent_type,
        "display_name": source.display_name,
    }
    if result is not None:
        payload.update(
            {
                "source_status": result.status,
                "reason_code": result.reason_code,
                "generated": len(result.facts),
                "duration_ms": duration_ms or 0,
            }
        )
    emit(payload)
