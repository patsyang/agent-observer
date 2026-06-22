from __future__ import annotations

import json
from pathlib import Path


def load_session_titles(codex_home: Path) -> dict[str, str]:
    path = codex_home / "session_index.jsonl"
    if not path.exists():
        return {}
    titles: dict[str, tuple[str, int, str]] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for index, line in enumerate(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = str(item.get("id") or "").strip()
        title = str(item.get("thread_name") or "").strip()
        if not session_id or not title:
            continue
        updated_at = str(item.get("updated_at") or "")
        current = titles.get(session_id)
        if current is None or (updated_at, index) >= (current[0], current[1]):
            titles[session_id] = (updated_at, index, title)
    return {session_id: item[2] for session_id, item in titles.items()}
