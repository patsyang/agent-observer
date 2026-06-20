from __future__ import annotations

import json

from app.collector_client.telemetry import collect_facts


def test_collector_collapses_duplicate_codex_message_projections(tmp_path):
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-20T10:00:00.100Z",
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "message": "同一条模型消息只应形成一个事实",
            },
        },
        {
            "timestamp": "2026-06-20T10:00:00.900Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "同一条模型消息只应形成一个事实"}],
            },
        },
    ]
    (sessions / "session-duplicate.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records),
        encoding="utf-8",
    )

    facts = collect_facts(
        "collector-codex",
        1,
        "safe_probe",
        codex_home=codex_home,
        history_window_days=7,
        max_events=20,
        cursor={"last_source_key": ""},
        upload_raw=True,
    )

    content_facts = [fact for fact in facts if fact["category"] == "codex_message"]

    assert len(content_facts) == 1
    fact = content_facts[0]
    assert fact["source_event_id"].startswith("codex-content-")
    assert fact["projection"]["record_type"] == "response_item"
    assert fact["source_specific"]["collapsed_event_types"] == [
        "event_msg:agent_message",
        "response_item:message",
    ]
    source_refs = fact["source_refs"]
    assert source_refs["source_key"].endswith("session-duplicate.jsonl:00000002")
    assert source_refs["alternate_source_keys"] == [
        f"{(sessions / 'session-duplicate.jsonl').as_posix()}:00000001"
    ]
