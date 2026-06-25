from __future__ import annotations

from typing import Callable

from app.collector_client.config import CollectorConfig
from app.collector_client.transport import _get_json


def confirm_batch_after_timeout(
    config: CollectorConfig,
    batch_id: str,
    *,
    emit_payload: Callable[[dict[str, object]], None],
    cycle: int | None,
) -> bool:
    emit_payload({"status": "ok", "mode": "upload_timeout_check", "cycle": cycle})
    status = _get_json(config.server_url, f"/api/telemetry/batches/{batch_id}")
    if status.get("status") != "accepted":
        emit_payload({"status": "error", "mode": "upload_timeout_missing", "cycle": cycle})
        return False
    emit_payload(
        {
            "status": "ok",
            "mode": "upload_timeout_confirmed",
            "cycle": cycle,
            "accepted": int(status.get("accepted_count") or 0),
        }
    )
    return True
