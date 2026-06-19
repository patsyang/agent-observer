from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.db.connection import connect


def test_concurrent_connections_initialize_schema_once_without_locking(tmp_path):
    db_path = tmp_path / "observer.sqlite"

    def read_collectors() -> int:
        with connect(db_path) as conn:
            return conn.execute("select count(*) from collectors").fetchone()[0]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: read_collectors(), range(24)))

    assert results == [0] * 24
