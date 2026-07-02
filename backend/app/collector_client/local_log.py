from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


Emit = Callable[[str], None]


def local_log_path(workdir: Path) -> Path:
    return workdir / "logs" / "collector.log"


def local_log_emit(workdir: Path, collector_id: str) -> Emit:
    path = local_log_path(workdir)

    def emit(line: str) -> None:
        try:
            payload = _payload_from_line(line)
            payload.setdefault("collector_id", collector_id)
            payload.setdefault("mode", payload.get("status", "event"))
            entry = {"logged_at": datetime.now(timezone.utc).isoformat(), **payload}
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass

    return emit


def _payload_from_line(line: str) -> dict[str, object]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return {"status": "ok", "mode": "message", "message": line}
    if isinstance(payload, dict):
        return payload
    return {"status": "ok", "mode": "message", "message": payload}
