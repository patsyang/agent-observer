from __future__ import annotations

from app.collector_client.config import SourceConfig
from app.collector_client.sources.base import SourceResult, stamp_source
from app.collector_client.telemetry import collect_facts

SOURCE_KIND = "codex_local"


def collect_codex_source(
    config: SourceConfig,
    *,
    collector_id: str,
    sequence: int,
    telemetry_mode: str,
    history_window_days: int,
    max_events: int,
    cursor: dict,
) -> SourceResult:
    facts = collect_facts(
        collector_id,
        sequence,
        telemetry_mode,
        codex_home=config.root,
        history_window_days=history_window_days,
        max_events=max_events,
        cursor=cursor,
    )
    status = "online" if config.root.exists() else "source_missing"
    reason = "collected" if status == "online" else "source_missing"
    return SourceResult(config=config, status=status, reason_code=reason, facts=stamp_source(facts, config))


collect = collect_codex_source
