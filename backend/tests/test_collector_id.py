from __future__ import annotations

import hashlib

from app.collector_client.config import _default_collector_id


def test_collector_id_for_ascii_user_and_hostname(monkeypatch):
    monkeypatch.setattr("getpass.getuser", lambda: "admin")
    monkeypatch.setattr("socket.gethostname", lambda: "server-01")

    collector_id = _default_collector_id()

    assert collector_id == "server-01-admin"


def test_collector_id_for_non_ascii_username_uses_hash(monkeypatch):
    monkeypatch.setattr("getpass.getuser", lambda: "张三")
    monkeypatch.setattr("socket.gethostname", lambda: "server-01")

    collector_id = _default_collector_id()

    expected_hash = hashlib.sha256("张三".encode("utf-8")).hexdigest()[:12]
    assert collector_id == f"collector-{expected_hash}"


def test_collector_id_replaces_url_unsafe_chars(monkeypatch):
    monkeypatch.setattr("getpass.getuser", lambda: "user@domain")
    monkeypatch.setattr("socket.gethostname", lambda: "server-01")

    collector_id = _default_collector_id()

    assert collector_id == "server-01-user-domain"
