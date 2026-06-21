from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.connection import connect
from app.facts.service import get_fact_detail, query_facts
from app.ingest.service import ingest_telemetry


def _fact(event_id: str, occurred_at: str, **overrides) -> dict:
    prompt_text = f"Prompt {event_id}"
    value = {
        "source_event_id": event_id,
        "fact_type": "content",
        "category": "codex_prompt",
        "quality": "high",
        "severity": "low",
        "summary": "记录到 Codex 用户 Prompt，已上传原始内容。",
        "occurred_at": occurred_at,
        "span": f"session:{event_id}",
        "raw_hash": f"hash-{event_id}",
        "projection": {"role": "user", "content_length": len(prompt_text), "prompt_text": prompt_text},
        "upload_raw": True,
        "raw_content": prompt_text,
        "source_refs": {
            "conversation_ref": f"conv-{event_id}",
            "session_ref": f"session-{event_id}",
            "source_path_hash": f"path-{event_id}",
        },
        "source_specific": {"codex_event_type": "message"},
    }
    value.update(overrides)
    return value


def _batch(batch_id: str, items: list[dict]) -> dict:
    return {
        "batch_id": batch_id,
        "protocol_version": "agent-observer-telemetry/v2",
        "agent_version": "0.2.0",
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": batch_id,
        "items": items,
    }


def test_query_facts_filters_time_window_and_hides_health_by_default(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                "batch-window-001",
                [
                    _fact("recent-prompt-001", (now - timedelta(minutes=5)).isoformat()),
                    _fact(
                        "recent-health-001",
                        (now - timedelta(minutes=3)).isoformat(),
                        fact_type="collector_health",
                        category="collector_health",
                        summary="采集器完成一次本机链路自检。",
                        span="collector:self-check",
                        projection={"collector_id": "collector-codex"},
                        source_refs={"collector_id": "collector-codex"},
                        source_specific={"probe": "collector_self_check"},
                    ),
                    _fact(
                        "old-error-001",
                        (now - timedelta(hours=2)).isoformat(),
                        fact_type="error",
                        category="codex_error",
                        severity="high",
                        summary="旧错误不应出现在 1 小时默认窗口。",
                        projection={"tool": "shell"},
                        source_specific={"codex_event_type": "tool_result"},
                    ),
                ],
            ),
        )
        default_result = query_facts(conn, window="1h", include_health=False)
        health_result = query_facts(conn, window="1h", include_health=True)
        all_result = query_facts(conn, window="all", include_health=True)

    assert [fact["fact_id"] for fact in default_result["facts"]] == ["recent-prompt-001"]
    assert default_result["total"] == 1
    assert default_result["facts"][0]["content_preview"] == "Prompt: Prompt recent-prompt-001"
    assert {fact["fact_id"] for fact in health_result["facts"]} == {"recent-prompt-001", "recent-health-001"}
    assert {fact["fact_id"] for fact in all_result["facts"]} >= {"recent-prompt-001", "recent-health-001", "old-error-001"}


def test_query_facts_can_filter_by_recent_ingest_time_for_backfill_visibility(tmp_path):
    old_event_time = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                "batch-backfill-visible",
                [_fact("backfill-prompt-001", old_event_time, summary="历史 Codex Prompt 刚刚完成回填。", projection={"role": "user", "content_length": 18})],
            ),
        )
        by_event_time = query_facts(conn, window="1h", include_health=False, time_basis="occurred")
        by_ingest_time = query_facts(conn, window="1h", include_health=False, time_basis="ingested")

    assert by_event_time["total"] == 0
    assert by_ingest_time["total"] == 1
    assert by_ingest_time["time_basis"] == "ingested"
    assert by_ingest_time["facts"][0]["fact_id"] == "backfill-prompt-001"
    assert by_ingest_time["facts"][0]["ingested_at"]


def test_query_facts_defaults_to_recent_event_time_not_backfill_ingest_time(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                "batch-event-time-default",
                [
                    _fact("old-backfill", (now - timedelta(days=1)).isoformat(), summary="旧事件刚入库"),
                    _fact("recent-event", (now - timedelta(minutes=1)).isoformat(), summary="最近发生的事件"),
                ],
            ),
        )
        result = query_facts(conn, window="1h", include_health=False)

    assert result["time_basis"] == "occurred"
    assert [fact["fact_id"] for fact in result["facts"]] == ["recent-event"]


def test_query_facts_hides_usage_even_when_requested(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                "batch-hide-usage",
                [
                    _fact(
                        "usage-hidden",
                        now.isoformat(),
                        fact_type="usage",
                        category="usage",
                        summary="用量事实不进入用户事实查询。",
                        projection={"activity_tag": "codex_turn", "units": 99},
                        usage={"units": 99, "activity_tag": "codex_turn"},
                    )
                ],
            ),
        )
        result = query_facts(conn, window="1h", include_health=True, fact_type="usage")

    assert result["total"] == 0
    assert result["facts"] == []


def test_ingest_populates_indexable_source_reference_columns(tmp_path):
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _batch("batch-source-columns", [_fact("source-columns", observed_at)]))
        row = conn.execute(
            """
            select conversation_ref, session_ref, source_event_type, source_path_hash
            from observed_facts
            where fact_id = ?
            """,
            ("source-columns",),
        ).fetchone()

    assert dict(row) == {
        "conversation_ref": "conv-source-columns",
        "session_ref": "session-source-columns",
        "source_event_type": "message",
        "source_path_hash": "path-source-columns",
    }


def test_default_fact_list_query_uses_event_time_index(tmp_path):
    observed_at = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                "batch-query-plan",
                [_fact(f"query-plan-{index}", (observed_at - timedelta(minutes=index)).isoformat()) for index in range(5)],
            ),
        )
        cutoff = (observed_at - timedelta(hours=1)).isoformat()
        plan = conn.execute(
            """
            explain query plan
            select * from observed_facts
            where fact_type != ? and occurred_at >= ?
            order by occurred_at desc, occurred_at desc, fact_id
            limit ? offset ?
            """,
            ("collector_health", cutoff, 50, 0),
        ).fetchall()

    details = " ".join(row[3] for row in plan)
    assert "idx_observed_facts_occurred_at" in details


def test_query_facts_returns_total_with_limit_and_offset(tmp_path):
    observed_at = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                "batch-pagination-001",
                [
                    _fact(
                        f"page-fact-{index:03d}",
                        (observed_at - timedelta(minutes=index)).isoformat(),
                        summary=f"分页事实 {index}",
                        span=f"session:page:{index}",
                        raw_hash=f"hash-page-{index:03d}",
                        projection={"role": "user", "content_length": index},
                        source_refs={"conversation_ref": "conv-page"},
                    )
                    for index in range(60)
                ],
            ),
        )
        first_page = query_facts(conn, window="1h", include_health=False, limit=50, offset=0)
        middle_page = query_facts(conn, window="1h", include_health=False, limit=10, offset=25)
        second_page = query_facts(conn, window="1h", include_health=False, limit=50, offset=50)

    assert first_page["total"] == 60
    assert first_page["limit"] == 50
    assert first_page["offset"] == 0
    assert len(first_page["facts"]) == 50
    assert first_page["facts"][0]["fact_id"] == "page-fact-000"
    assert middle_page["offset"] == 25
    assert len(middle_page["facts"]) == 10
    assert middle_page["facts"][0]["fact_id"] == "page-fact-025"
    assert second_page["total"] == 60
    assert second_page["offset"] == 50
    assert len(second_page["facts"]) == 10
    assert second_page["facts"][0]["fact_id"] == "page-fact-050"


def test_low_evidence_preview_uses_event_shape_instead_of_generic_boilerplate(tmp_path):
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                "batch-low-preview",
                [
                    _fact(
                        "low-preview-001",
                        observed_at,
                        fact_type="unknown",
                        category="uncategorized",
                        quality="low",
                        summary="Codex 会话出现未归类但来源合法的低证据事件，已保留为低证据命中候选。",
                        projection={
                            "payload_type": "response_item",
                            "observed_keys": ["timestamp", "type", "payload"],
                            "payload_keys": ["type", "content", "role"],
                        },
                    )
                ],
            ),
        )
        result = query_facts(conn, window="1h", include_health=False)

    preview = result["facts"][0]["content_preview"]
    assert preview == "未归类 Codex 事件：事件类型 response_item，可用字段 type, content, role"
    assert "低证据命中候选" not in preview


def test_ingest_stores_raw_evidence_when_projection_upload_raw_is_enabled(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        result = ingest_telemetry(
            conn,
            _batch(
                "raw-batch-001",
                [
                    {
                        "source_event_id": "raw-event-001",
                        "fact_type": "error",
                        "category": "codex_error",
                        "quality": "high",
                        "severity": "high",
                        "summary": "Codex 工具失败，已上传原始证据。",
                        "occurred_at": "2026-06-18T10:00:00+00:00",
                        "span": "session:raw",
                        "raw_hash": "hash-raw-001",
                        "projection": {"tool": "shell"},
                        "evidence_projections": [
                            {
                                "projection_id": "proj-raw-001",
                                "category": "codex_error",
                                "span": "session:raw:line1",
                                "raw_hash": "hash-raw-001",
                                "projection": {"tool": "shell"},
                                "upload_raw": True,
                                "raw_content": "raw log prompt token auth content for operator diagnosis",
                            }
                        ],
                        "source_refs": {"conversation_ref": "conv-raw"},
                        "source_specific": {"codex_event_type": "tool_result"},
                    }
                ],
            ),
        )
        detail = get_fact_detail(conn, "raw-event-001")

    assert result["accepted"] == 1
    assert detail["evidence_projection"]["upload_raw"] is True
    assert detail["evidence_projection"]["raw_content"] == "raw log prompt token auth content for operator diagnosis"
