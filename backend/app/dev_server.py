from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.dashboard.service import get_dashboard_summary
from app.db.connection import connect
from app.dev_server_handlers import (
    _conversations_query_options,
    _path_part,
    _stories_query_options,
    handle_delete,
    handle_get,
    handle_patch,
    handle_post,
)


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            return

    def do_OPTIONS(self) -> None:
        self._json(200, {})

    def do_GET(self) -> None:
        handle_get(self)

    def do_PATCH(self) -> None:
        handle_patch(self)

    def do_DELETE(self) -> None:
        handle_delete(self)

    def do_POST(self) -> None:
        handle_post(self)


def get_server_port() -> int:
    return int(os.environ.get("AGENT_OBSERVER_PORT", "8765"))


if __name__ == "__main__":
    with connect() as conn:
        get_dashboard_summary(conn, window="1h")
    ThreadingHTTPServer(("127.0.0.1", get_server_port()), Handler).serve_forever()
