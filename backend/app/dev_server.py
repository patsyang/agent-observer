from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

from app.dashboard.service import get_dashboard_summary
from app.db.connection import connect, default_db_path
from app.dev_server_handlers import (
    _conversations_query_options,
    _path_part,
    _signals_query_options,
    handle_delete,
    handle_get,
    handle_patch,
    handle_post,
)
from app.log import apply_log_level, is_poll_path, setup_logging
from app.policy import get_effective_policy
from app.processing.worker import start_processing_worker

logger = logging.getLogger("agent-observer.app.dev_server")


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

    def log_message(self, format, *args):
        msg = format % args
        path = msg.split()[1] if len(msg.split()) > 1 else ""
        client_ip = self.client_address[0] if self.client_address else "-"
        log_msg = f"{client_ip} {msg}"
        if is_poll_path(path):
            logger.debug(log_msg)
        else:
            logger.info(log_msg)

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


def get_otlp_port() -> int:
    return int(os.environ.get("AGENT_OBSERVER_OTLP_PORT", "4318"))


def _start_otlp_server(otlp_port: int) -> None:
    """在守护线程中启动 OTLP 接收端点（4318）。"""
    from app.otlp.router import OtlpHandler
    try:
        otlp_server = HTTPServer(("127.0.0.1", otlp_port), OtlpHandler)
        logger.info("OTLP 接收端点: http://127.0.0.1:%d/v1/logs", otlp_port)
        otlp_server.serve_forever()
    except OSError as exc:
        if "address already in use" in str(exc).lower():
            logger.error("OTLP 端口 %d 已被占用，codex 遥测将被丢弃", otlp_port)
        else:
            raise


if __name__ == "__main__":
    db_path = default_db_path()
    server_logger = setup_logging(db_path)
    with connect() as conn:
        policy = get_effective_policy(conn)
        apply_log_level(policy.get("log_level", "INFO"))
        get_dashboard_summary(conn, window="1h")
    port = get_server_port()
    otlp_port = get_otlp_port()
    server_logger.info("agent-observer server starting on :%d, db=%s, pid=%d", port, db_path, os.getpid())
    start_processing_worker()
    # 启动 OTLP 接收端点（4318）在守护线程中
    otlp_thread = threading.Thread(target=_start_otlp_server, args=(otlp_port,), daemon=True)
    otlp_thread.start()
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
