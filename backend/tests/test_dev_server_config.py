from app.dev_server import get_server_port


def test_dev_server_port_defaults_to_business_port(monkeypatch):
    monkeypatch.delenv("AGENT_OBSERVER_PORT", raising=False)

    assert get_server_port() == 8765


def test_dev_server_port_can_be_overridden_for_e2e(monkeypatch):
    monkeypatch.setenv("AGENT_OBSERVER_PORT", "8766")

    assert get_server_port() == 8766
