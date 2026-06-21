from __future__ import annotations

import pytest


def test_fastapi_main_exposes_dashboard_and_pagination(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AGENT_OBSERVER_DB", str(tmp_path / "observer.sqlite"))
    from app.main import create_app

    client = TestClient(create_app())

    summary = client.get("/api/dashboard/summary?window=1h")
    conversations = client.get("/api/conversations?window=1h&page=1&page_size=10")
    stories = client.get("/api/stories?window=1h&page=1&page_size=10&queue=actionable")

    assert summary.status_code == 200
    assert summary.json()["window"] == "1h"
    assert conversations.status_code == 200
    assert conversations.json()["page"] == 1
    assert conversations.json()["page_size"] == 10
    assert stories.status_code == 200
    assert stories.json()["page"] == 1
    assert stories.json()["page_size"] == 10
