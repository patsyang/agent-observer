from __future__ import annotations

from app.dev_server_handlers import _conversations_query_options, _path_part, _signals_query_options, _summary_query_options


def test_dev_server_forwards_signal_window_filters():
    options = _signals_query_options("/api/signals?window=24h&page=2&page_size=10")

    assert options == {
        "window": "24h",
        "start_at": None,
        "end_at": None,
        "page": 2,
        "page_size": 10,
    }


def test_dev_server_forwards_conversation_filters_and_decodes_path_refs():
    options = _conversations_query_options(
        "/api/conversations?window=all&prompt_query=hello&response_query=world&start_at=2026-06-21T01%3A00%3A00.000Z"
    )

    assert options == {
        "window": "all",
        "start_at": "2026-06-21T01:00:00.000Z",
        "end_at": None,
        "prompt_query": "hello",
        "response_query": "world",
        "agent_type": None,
        "source_id": None,
        "page": 1,
        "page_size": 20,
    }
    assert _path_part("/api/conversations/ref%3Aconversation-1", 3) == "ref:conversation-1"


def test_dev_server_forwards_summary_custom_range_filters():
    options = _summary_query_options(
        "/api/usage/summary?window=custom&agent_type=workbuddy&start_at=2026-06-21T01%3A00%3A00Z&end_at=2026-06-21T03%3A00%3A00Z",
        "24h",
    )

    assert options == {
        "window": "custom",
        "agent_type": "workbuddy",
        "start_at": "2026-06-21T01:00:00Z",
        "end_at": "2026-06-21T03:00:00Z",
    }
