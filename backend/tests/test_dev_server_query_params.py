from __future__ import annotations

from app.dev_server import _facts_query_options, _stories_query_options


def test_dev_server_forwards_fact_window_and_health_filters():
    options = _facts_query_options("/api/facts?quality=low&window=1h&include_health=false")

    assert options == {
        "quality": "low",
        "fact_type": None,
        "source": None,
        "window": "1h",
        "include_health": False,
        "limit": 50,
        "offset": 0,
    }


def test_dev_server_forwards_story_window_and_queue_filters():
    options = _stories_query_options("/api/stories?window=24h&queue=actionable&include_hidden=true")

    assert options == {
        "include_hidden": True,
        "window": "24h",
        "queue": "actionable",
    }
