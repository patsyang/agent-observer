from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

from app.collector_client.version import COLLECTOR_CLIENT_VERSION, COLLECTOR_PROTOCOL_VERSION
APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"


def get_public_server_url() -> str:
    return os.environ.get("AGENT_OBSERVER_PUBLIC_BASE_URL", DEFAULT_SERVER_URL).rstrip("/")


def build_windows_package(conn, output_dir: str | Path = "data/packages") -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    config_path = out / "agent-observer.config.json"
    package_path = out / "agent-observer-windows.zip"
    config = {
        "server_url": get_public_server_url(),
        "collector_id": "windows-collector",
        "state_path": "agent-observer.state.json",
        "telemetry_mode": "safe_probe",
        "collection_interval_seconds": 5,
        "heartbeat_interval_seconds": 10,
        "sources": [
            {
                "source_id": "codex-local",
                "agent_type": "codex",
                "source_kind": "codex_local",
                "display_name": "Codex Local",
                "root": "%USERPROFILE%\\.codex",
                "enabled": True,
            },
            {
                "source_id": "workbuddy-local",
                "agent_type": "workbuddy",
                "source_kind": "workbuddy_local",
                "display_name": "WorkBuddy Local",
                "root": "%USERPROFILE%\\.workbuddy",
                "enabled": True,
            },
        ],
        "history_window_days": 7,
        "max_events_per_cycle": 500,
        "upload_batch_size": 100,
        "evidence_mode": "structured_projection",
        "agent_version": COLLECTOR_CLIENT_VERSION,
        "protocol_version": COLLECTOR_PROTOCOL_VERSION,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "agent-observer.cmd",
            (
                "@echo off\r\n"
                "setlocal\r\n"
                'cd /d "%~dp0"\r\n'
                'set "PYTHONPATH=%CD%;%PYTHONPATH%"\r\n'
                "python -m app.collector_client.cli %*\r\n"
                "exit /b %ERRORLEVEL%\r\n"
            ),
        )
        archive.writestr("agent-observer.config.json", config_path.read_text(encoding="utf-8"))
        archive.writestr("README.txt", "Agent Observer Windows collector package\n")
        archive.write(APP_ROOT / "__init__.py", "app/__init__.py")
        archive.write(APP_ROOT / "sensitivity.py", "app/sensitivity.py")
        for path in sorted((APP_ROOT / "collector_client").glob("*.py")):
            archive.write(path, f"app/collector_client/{path.name}")
        for path in sorted((APP_ROOT / "collector_client" / "sources").glob("*.py")):
            archive.write(path, f"app/collector_client/sources/{path.name}")
    checksum = hashlib.sha256(package_path.read_bytes()).hexdigest()
    return {
        "filename": "agent-observer-windows.zip",
        "path": str(package_path),
        "sha256": checksum,
        "server_url": config["server_url"],
        "agent_version": COLLECTOR_CLIENT_VERSION,
        "protocol_version": COLLECTOR_PROTOCOL_VERSION,
    }
