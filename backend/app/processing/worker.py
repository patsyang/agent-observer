from __future__ import annotations

import threading
import time

from app.db.connection import connect
from app.policy import DEFAULT_WORKER_POLL_INTERVAL_SECONDS, get_effective_policy
from app.processing.jobs import run_next_job

_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def start_processing_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        thread = threading.Thread(target=_worker_loop, name="agent-observer-processing-worker", daemon=True)
        thread.start()
        _WORKER_STARTED = True


def _worker_loop() -> None:
    while True:
        interval = DEFAULT_WORKER_POLL_INTERVAL_SECONDS
        try:
            with connect() as conn:
                policy = get_effective_policy(conn)
                interval = int(policy.get("worker_poll_interval_seconds") or interval)
                run_next_job(conn, reason="worker")
        except Exception:
            pass
        time.sleep(max(2, min(interval, 300)))
