from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_ROOT = Path("apps/agentic_factory")
PORTS = (8888, 9999)


def dev(repo_root: Path) -> int:
    if stop_dev(repo_root) != 0:
        return 1
    occupied = _listening_pids(PORTS)
    if occupied:
        print(f"Dev ports are occupied by unmanaged PIDs: {sorted(occupied)}", file=sys.stderr)
        return 1
    log_dir = repo_root / "output/dev-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    api_log = (log_dir / "api.log").open("w", encoding="utf-8")
    web_log = (log_dir / "web.log").open("w", encoding="utf-8")
    processes = _start_dev_processes(repo_root, api_log, web_log)
    _write_pid_file(log_dir / "dev-pids.txt", processes)
    print("API: http://127.0.0.1:8888")
    print("Web: http://127.0.0.1:9999")
    print(f"Logs: {log_dir}")
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping dev services...")
    finally:
        api_log.close()
        web_log.close()
        stop_dev(repo_root)
    return 0


def stop_dev(repo_root: Path) -> int:
    pid_file = repo_root / "output/dev-logs/dev-pids.txt"
    managed_pids = _read_pid_file(pid_file)
    for pid in sorted(managed_pids):
        _taskkill(pid)
    time.sleep(1)
    remaining_managed = managed_pids & _listening_pids(PORTS)
    if remaining_managed:
        print(
            f"Managed dev ports are still listening: {sorted(remaining_managed)}",
            file=sys.stderr,
        )
        return 1
    if pid_file.exists():
        pid_file.unlink()
    print("Dev services stopped.")
    return 0


def status_dev(repo_root: Path) -> int:
    managed_pids = _read_pid_file(repo_root / "output/dev-logs/dev-pids.txt")
    listeners = _listening_pids(PORTS)
    if not listeners:
        print("No Agentic Factory dev services are listening on 8888/9999.")
        return 0
    unmanaged = listeners - managed_pids
    for port in PORTS:
        print(f"Port {port}: {'listening' if _port_open(port) else 'not listening'}")
    print(f"Managed PIDs: {', '.join(str(pid) for pid in sorted(managed_pids)) or 'none'}")
    print(f"Listening PIDs: {', '.join(str(pid) for pid in sorted(listeners))}")
    if unmanaged:
        print(f"Unmanaged listeners: {', '.join(str(pid) for pid in sorted(unmanaged))}")
    print(f"API health: {_http_status('http://127.0.0.1:8888/health')}")
    print(f"Web status: {_http_status('http://127.0.0.1:9999')}")
    return 0


def _start_dev_processes(repo_root: Path, api_log, web_log) -> list[subprocess.Popen[str]]:
    app = repo_root / APP_ROOT
    api_command = [
        "uv",
        "run",
        "--project",
        str(app / "backend"),
        "uvicorn",
        "agentic_factory_api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8888",
    ]
    web_command = [
        "npm",
        "--prefix",
        str(app / "frontend"),
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "9999",
    ]
    return [
        subprocess.Popen(
            _resolve_command(api_command),
            cwd=repo_root,
            stdout=api_log,
            stderr=subprocess.STDOUT,
            text=True,
        ),
        subprocess.Popen(
            _resolve_command(web_command),
            cwd=repo_root,
            stdout=web_log,
            stderr=subprocess.STDOUT,
            text=True,
        ),
    ]


def _resolve_command(command: list[str]) -> list[str]:
    executable = shutil.which(command[0])
    return [executable, *command[1:]] if executable else command


def _write_pid_file(path: Path, processes: list[subprocess.Popen[str]]) -> None:
    lines = [f"process_{index}={process.pid}" for index, process in enumerate(processes, start=1)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_pid_file(path: Path) -> set[int]:
    if not path.exists():
        return set()
    pids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.partition("=")[2].strip()
        if value.isdigit():
            pids.add(int(value))
    return pids


def _listening_pids(ports: tuple[int, ...]) -> set[int]:
    result = subprocess.run(
        _resolve_command(["netstat", "-ano", "-p", "tcp"]),
        capture_output=True,
        text=True,
        check=False,
    )
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            local = parts[1].rsplit(":", 1)
            if _is_target_listener(local, parts, ports):
                pids.add(int(parts[4]))
    return pids


def _is_target_listener(local: list[str], parts: list[str], ports: tuple[int, ...]) -> bool:
    return (
        len(local) == 2
        and local[1].isdigit()
        and int(local[1]) in ports
        and parts[4].isdigit()
    )


def _taskkill(pid: int) -> None:
    subprocess.run(
        _resolve_command(["taskkill", "/PID", str(pid), "/T", "/F"]),
        check=False,
        capture_output=True,
        text=True,
    )


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _http_status(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return str(response.status)
    except urllib.error.URLError:
        return "not responding"
