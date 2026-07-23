"""OTLP HTTP 接收端点：处理 /v1/logs 请求。"""
from __future__ import annotations

import gzip
import json
import logging
from http.server import BaseHTTPRequestHandler

from app.db.connection import write_lock
from app.otlp.service import process_otlp_logs

logger = logging.getLogger(__name__)
_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB


class OtlpHandler(BaseHTTPRequestHandler):
    """OTLP HTTP 协议处理器。"""

    def do_POST(self) -> None:
        if self.path == "/v1/logs":
            self._handle_logs()
        elif self.path in ("/v1/traces", "/v1/metrics"):
            # codex 可能也导出 traces/metrics，返回 200 防止重试
            self._read_body_discard()
            self._respond(200, {"success": {}})
        else:
            self._respond(404, {"error": "not_found"})

    def _handle_logs(self) -> None:
        try:
            body = self._read_body()
            if body is None:
                return
            data = json.loads(body) if body else {}
            with write_lock() as conn:
                result = process_otlp_logs(conn, data)
            self._respond(200, {"success": {}, **result})
        except json.JSONDecodeError as exc:
            logger.warning("OTLP JSON 解析失败: %s", exc)
            self._respond(400, {"error": "invalid_json"})
        except Exception as exc:
            logger.exception("OTLP 处理失败")
            self._respond(500, {"error": str(exc)})

    def _read_body(self) -> str | None:
        length = int(self.headers.get("Content-Length", 0))
        if length > _MAX_BODY_SIZE:
            self._respond(413, {"error": "body_too_large"})
            return None
        if length == 0:
            return ""
        raw = self.rfile.read(length)
        encoding = self.headers.get("Content-Encoding", "").lower()
        if "gzip" in encoding:
            try:
                raw = gzip.decompress(raw)
            except OSError:
                self._respond(400, {"error": "invalid_gzip"})
                return None
        content_type = self.headers.get("Content-Type", "").lower()
        if "protobuf" in content_type:
            self._respond(415, {"error": "unsupported_media_type",
                               "hint": "请配置 protocol = json"})
            return None
        return raw.decode("utf-8")

    def _read_body_discard(self) -> None:
        """读取并丢弃请求体（用于 traces/metrics 端点）。"""
        length = int(self.headers.get("Content-Length", 0))
        if 0 < length <= _MAX_BODY_SIZE:
            self.rfile.read(length)

    def _respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        logger.info("OTLP %s - %s", self.address_string(), format % args)
