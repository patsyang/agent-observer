from __future__ import annotations

import pytest

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.conversations.materialize import prune_before
from app.conversations.service import query_conversations
from source_payloads import default_versions


def _batch(items, batch_id="b1"):
    return {
        "batch_id": batch_id,
        **default_versions(),
        "collector_id": "c1",
        "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
        "cursor": "cur",
        "items": items,
    }


def _item(
    eid, fact_type, category, occ, *, projection=None, raw=None, usage=None, conv="conv1", line=None
):
    refs = {"conversation_ref": conv}
    if line is not None:
        refs["line"] = line
    item = {
        "source_event_id": eid,
        "fact_type": fact_type,
        "category": category,
        "summary": "s",
        "occurred_at": occ,
        "raw_hash": f"h-{eid}",
        "source_refs": refs,
        "source_specific": {"event_type": "x"},
    }
    if projection is not None:
        item["projection"] = projection
    if raw is not None:
        item["raw_content"] = raw
    if usage is not None:
        item["usage"] = usage
    return item


def test_token_accumulation_and_cache_hit_rate(tmp_path):
    with connect(tmp_path / "obs.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                [
                    _item("e1", "content", "agent_prompt", "2026-07-04T01:00:00+00:00", projection={"prompt_text": "hi"}, raw="hi"),
                    _item("e2", "content", "agent_response", "2026-07-04T02:00:00+00:00", projection={"content_text": "yo"}, raw="yo"),
                    _item("e3", "usage", "usage", "2026-07-04T03:00:00+00:00", usage={"scope": "s", "units": 10, "input_tokens": 100, "cached_input_tokens": 60, "cache_observed": 1, "output_tokens": 40, "total_tokens": 140}),
                    _item("e4", "usage", "usage", "2026-07-04T04:00:00+00:00", usage={"scope": "s", "units": 5, "input_tokens": 50, "cached_input_tokens": 50, "cache_observed": 1, "output_tokens": 10, "total_tokens": 60}),
                ]
            ),
        )
        r = conn.execute("select * from conversations where conversation_ref = 'conv1'").fetchone()
        assert r["model_call_count"] == 2
        assert r["effective_units"] == 15
        assert r["input_token_units"] == 150
        assert r["cached_input_units"] == 110
        assert r["cache_observed_input_units"] == 150
        assert r["cache_hit_rate"] == round(110 / 150, 4)
        assert r["max_single_call_units"] == 10


def test_dedup_refreshes_content_without_double_counting(tmp_path):
    with connect(tmp_path / "obs.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                [
                    _item("e1", "content", "agent_prompt", "2026-07-04T01:00:00+00:00", projection={"prompt_text": "hi"}, raw="hi"),
                    _item("e2", "content", "agent_response", "2026-07-04T02:00:00+00:00", projection={"content_text": "yo"}, raw="yo"),
                ]
            ),
        )
        # dedup：重传 e2，带新 raw_content
        ingest_telemetry(
            conn,
            _batch(
                [
                    _item("e2", "content", "agent_response", "2026-07-04T02:00:00+00:00", projection={"content_text": "yo updated"}, raw="yo updated"),
                ],
                batch_id="b2",
            ),
        )
        r = conn.execute("select * from conversations where conversation_ref = 'conv1'").fetchone()
        # dedup 不新增 fact → event_count 不翻倍
        assert r["event_count"] == 2
        # response content 已刷新
        assert r["response_preview"] == "yo updated"
        # 只剩一条 assistant 消息
        assert conn.execute(
            "select count(*) from conversation_messages where conversation_ref = 'conv1' and role = 'assistant'"
        ).fetchone()[0] == 1
        # FTS 同步刷新（无重复）
        assert conn.execute(
            "select count(*) from conversation_messages_fts where conversation_ref = 'conv1' and role = 'assistant'"
        ).fetchone()[0] == 1


def test_prune_removes_conversation_and_dependents(tmp_path):
    with connect(tmp_path / "obs.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                [
                    _item("e1", "content", "agent_prompt", "2026-06-01T01:00:00+00:00", projection={"prompt_text": "old"}, raw="old", conv="conv-old"),
                    _item("e2", "content", "agent_response", "2026-06-01T02:00:00+00:00", projection={"content_text": "old r"}, raw="old r", conv="conv-old"),
                    _item("e3", "content", "agent_prompt", "2026-07-04T01:00:00+00:00", projection={"prompt_text": "new"}, raw="new", conv="conv-new"),
                    _item("e4", "content", "agent_response", "2026-07-04T02:00:00+00:00", projection={"content_text": "new r"}, raw="new r", conv="conv-new"),
                ]
            ),
        )
        deleted = prune_before(conn, "2026-07-01T00:00:00+00:00")
        conn.commit()
        assert deleted == 1
        refs = [row["conversation_ref"] for row in conn.execute("select conversation_ref from conversations")]
        assert "conv-new" in refs
        assert "conv-old" not in refs
        assert conn.execute("select count(*) from conversation_messages where conversation_ref = 'conv-old'").fetchone()[0] == 0
        assert conn.execute("select count(*) from conversation_hits where conversation_ref = 'conv-old'").fetchone()[0] == 0
        assert conn.execute("select count(*) from conversation_messages_fts where conversation_ref = 'conv-old'").fetchone()[0] == 0


def test_rebuild_idempotent(tmp_path):
    from scripts.rebuild_conversations import rebuild

    with connect(tmp_path / "obs.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                [
                    _item("e1", "content", "agent_prompt", "2026-07-04T01:00:00+00:00", projection={"prompt_text": "hi"}, raw="hi"),
                    _item("e2", "content", "agent_response", "2026-07-04T02:00:00+00:00", projection={"content_text": "yo"}, raw="yo"),
                    _item("e3", "usage", "usage", "2026-07-04T03:00:00+00:00", usage={"scope": "s", "units": 7, "input_tokens": 10, "cache_observed": 0}),
                ]
            ),
        )
        online = query_conversations(conn, window="all")["conversations"]
        rebuild(conn, batch_size=100, sleep_seconds=0)
        rebuilt1 = query_conversations(conn, window="all")["conversations"]
        rebuild(conn, batch_size=100, sleep_seconds=0)
        rebuilt2 = query_conversations(conn, window="all")["conversations"]
        assert online == rebuilt1 == rebuilt2


def test_out_of_order_arrival_keeps_correct_preview(tmp_path):
    # 先到 response，后到 prompt（乱序）：preview 仍取最早 prompt/response
    with connect(tmp_path / "obs.sqlite") as conn:
        ingest_telemetry(
            conn,
            _batch(
                [_item("e2", "content", "agent_response", "2026-07-04T02:00:00+00:00", projection={"content_text": "later resp"}, raw="later resp")],
                batch_id="b1",
            ),
        )
        ingest_telemetry(
            conn,
            _batch(
                [_item("e1", "content", "agent_prompt", "2026-07-04T01:00:00+00:00", projection={"prompt_text": "earlier prompt"}, raw="earlier prompt")],
                batch_id="b2",
            ),
        )
        r = conn.execute("select * from conversations where conversation_ref = 'conv1'").fetchone()
        assert r["prompt_preview"] == "earlier prompt"
        assert r["response_preview"] == "later resp"
        assert r["started_at"] == "2026-07-04T01:00:00+00:00"
        assert r["last_event_at"] == "2026-07-04T02:00:00+00:00"
