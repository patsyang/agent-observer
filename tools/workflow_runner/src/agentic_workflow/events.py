import json
from datetime import UTC, datetime
from pathlib import Path


def append_event(
    event_path: Path,
    *,
    run_id: str,
    workflow: str,
    step: str,
    status: str,
    message: str,
    artifact_path: str | None = None,
    duration_ms: int | None = None,
) -> None:
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "workflow": workflow,
        "step": step,
        "status": status,
        "message": message,
        "artifact_path": artifact_path,
        "duration_ms": duration_ms,
    }
    with event_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")
