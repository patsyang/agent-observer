from __future__ import annotations

import sqlite3


def get_batch_status(conn: sqlite3.Connection, batch_id: str) -> dict:
    row = conn.execute(
        """
        select batch_id, accepted_count, duplicate_count, created_at
        from telemetry_batches
        where batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        return {"batch_id": batch_id, "status": "missing"}
    return {
        "batch_id": row["batch_id"],
        "status": "accepted",
        "accepted_count": row["accepted_count"],
        "duplicate_count": row["duplicate_count"],
        "created_at": row["created_at"],
    }
