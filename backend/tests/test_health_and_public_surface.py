from __future__ import annotations

from app.collectors.service import register_collector
from app.db.connection import connect
from app.package.builder import build_windows_package
from source_payloads import default_sources, default_versions


def test_stack_ref_and_public_surface_without_forbidden_routes(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        package = build_windows_package(conn, tmp_path / "packages")
        result = register_collector(
            conn,
            {
                "hostname": "host",
                "windows_username": "user",
                "agent_type": "codex",
                **default_versions(),
                "sources": default_sources(),
            },
        )

    assert result["effective_policy"]["policy_version"] == 1
    assert package["filename"] == "agent-observer-windows.zip"
    forbidden = ["login", "permission", "remote start", "remote stop", "arbitrary command"]
    public_surface = "collectors policy client-package status doctor"
    for phrase in forbidden:
        assert phrase not in public_surface
