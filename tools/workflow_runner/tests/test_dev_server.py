from pathlib import Path

from agentic_workflow import dev_server


def test_stop_dev_does_not_kill_unmanaged_port_listener(tmp_path: Path, monkeypatch) -> None:
    killed = []
    monkeypatch.setattr(dev_server, "_listening_pids", lambda _ports: {1234})
    monkeypatch.setattr(dev_server, "_taskkill", lambda pid: killed.append(pid))
    monkeypatch.setattr(dev_server.time, "sleep", lambda _seconds: None)

    assert dev_server.stop_dev(tmp_path) == 0
    assert killed == []


def test_stop_dev_kills_only_pid_file_entries(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "output/dev-logs/dev-pids.txt"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("api=111\nweb=222\n", encoding="utf-8")
    killed = []
    monkeypatch.setattr(dev_server, "_listening_pids", lambda _ports: set())
    monkeypatch.setattr(dev_server, "_taskkill", lambda pid: killed.append(pid))
    monkeypatch.setattr(dev_server.time, "sleep", lambda _seconds: None)

    assert dev_server.stop_dev(tmp_path) == 0
    assert killed == [111, 222]
