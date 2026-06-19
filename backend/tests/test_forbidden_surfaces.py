from __future__ import annotations

from pathlib import Path


FORBIDDEN_TERMS = (
    "login",
    "permissions",
    "message inbox",
    "collector disable",
    "remote client start",
    "remote client stop",
    "arbitrary command",
    "arbitrary sql",
    "arbitrary file read",
    "manual upload",
    "state reset",
    "outbox cleanup",
    "historical story snapshot",
    "standalone audit center",
)


def test_forbidden_surfaces_are_absent_from_runtime_ui_api_and_command_copy():
    repo = Path(__file__).resolve().parents[2]
    runtime_files = [
        *repo.glob("frontend/src/**/*.tsx"),
        *repo.glob("frontend/src/**/*.ts"),
        *repo.glob("backend/app/**/*.py"),
        repo / "scripts/ao.py",
    ]
    checked = []
    matches = []
    for path in runtime_files:
        if path.name.endswith(".test.tsx") or path.name.endswith(".test.ts"):
            continue
        text = path.read_text(encoding="utf-8").lower()
        checked.append(str(path.relative_to(repo)))
        for term in FORBIDDEN_TERMS:
            if term in text:
                matches.append(f"{path.relative_to(repo)} contains {term}")

    assert checked
    assert matches == []
