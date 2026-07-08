from __future__ import annotations

from app.dev_server_handlers import _conversations_query_options, _path_part, _query_int, _signals_query_options, _summary_query_options


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


def test_dev_server_forwards_signal_family_filter():
    options = _signals_query_options("/api/signals?window=24h&family=behavior_anomaly")
    assert options["family"] == "behavior_anomaly"


def test_dev_server_routes_summary_before_signal_id_catchall(tmp_path, monkeypatch):
    """`/api/signals/summary` must hit signal_summary, not be swallowed as a signal_id."""
    monkeypatch.setenv("AGENT_OBSERVER_DB", str(tmp_path / "observer.sqlite"))
    from app.dev_server_handlers import handle_get

    class _Stub:
        def __init__(self, path: str) -> None:
            self.path = path
            self.status = None
            self.payload = None

        def _json(self, status: int, payload: dict) -> None:
            self.status = status
            self.payload = payload

    summary = _Stub("/api/signals/summary?window=all")
    handle_get(summary)
    assert summary.status == 200
    assert "families" in summary.payload

    taxonomy = _Stub("/api/risk-taxonomy")
    handle_get(taxonomy)
    assert taxonomy.status == 200
    assert "kind_to_family" in taxonomy.payload


def test_query_int_returns_default_for_non_numeric():
    """非数字 page/page_size 输入回退为默认值，不抛异常。"""
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse("/api/conversations?page=abc&page_size=xyz").query)
    assert _query_int(query, "page", 1) == 1
    assert _query_int(query, "page_size", 50) == 50

    query_valid = parse_qs(urlparse("/api/conversations?page=3&page_size=25").query)
    assert _query_int(query_valid, "page", 1) == 3
    assert _query_int(query_valid, "page_size", 50) == 25


def test_conversations_query_options_non_numeric_page_uses_default():
    """_conversations_query_options 在 page/page_size 非数字时使用默认值。"""
    options = _conversations_query_options("/api/conversations?page=abc&page_size=xyz")
    assert options["page"] == 1
    assert options["page_size"] == 20

