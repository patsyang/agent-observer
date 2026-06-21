from __future__ import annotations

from app.dev_server import _conversations_query_options, _path_part, _stories_query_options


def test_dev_server_forwards_story_window_and_queue_filters():
    options = _stories_query_options("/api/stories?window=24h&queue=actionable&include_hidden=true")

    assert options == {
        "include_hidden": True,
        "window": "24h",
        "queue": "actionable",
        "page": 1,
        "page_size": 20,
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
        "page": 1,
        "page_size": 50,
    }
    assert _path_part("/api/conversations/ref%3Aconversation-1", 3) == "ref:conversation-1"
