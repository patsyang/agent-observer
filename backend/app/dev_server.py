from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.collectors.service import (
    delete_collector,
    heartbeat,
    list_collectors,
    register_collector,
    update_collector_display_name,
    update_collector_raw_upload,
)
from app.db.connection import connect
from app.diagnostics.service import (
    cancel_diagnostic,
    get_diagnostic_availability,
    get_next_collector_diagnostic,
    record_collector_diagnostic_result,
    record_diagnostic_result,
    request_diagnostic,
)
from app.facts.service import get_fact_detail, query_facts
from app.ingest.service import ingest_telemetry
from app.package.builder import build_windows_package
from app.policy import get_effective_policy, recent_audit, update_effective_policy
from app.risks.service import get_risk_summary
from app.stories.service import get_story_detail, handle_story, list_stories, mark_story_read, rebuild_stories
from app.usage.service import get_usage_summary
from app.validation.service import run_minimum_validation_experiment


def _query_one(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    return (query.get(key) or [default])[0]


def _query_bool(query: dict[str, list[str]], key: str, default: bool = False) -> bool:
    value = _query_one(query, key)
    if value is None:
        return default
    return value.lower() == "true"


def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
    value = _query_one(query, key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _facts_query_options(raw_path: str) -> dict:
    query = parse_qs(urlparse(raw_path).query)
    return {
        "quality": _query_one(query, "quality"),
        "fact_type": _query_one(query, "fact_type"),
        "source": _query_one(query, "source"),
        "window": _query_one(query, "window", "1h"),
        "include_health": _query_bool(query, "include_health", False),
        "limit": _query_int(query, "limit", 50),
        "offset": _query_int(query, "offset", 0),
    }


def _stories_query_options(raw_path: str) -> dict:
    query = parse_qs(urlparse(raw_path).query)
    return {
        "include_hidden": _query_bool(query, "include_hidden", False),
        "window": _query_one(query, "window", "all"),
        "queue": _query_one(query, "queue", "all"),
    }


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
        path = urlparse(self.path).path
        with connect() as conn:
            if path == "/api/collectors":
                self._json(200, {"collectors": list_collectors(conn)})
                return
            if path.startswith("/api/collectors/") and path.endswith("/diagnostics/next"):
                try:
                    self._json(200, get_next_collector_diagnostic(conn, path.split("/")[3]))
                except LookupError:
                    self._json(404, {"error": "collector not found"})
                return
            if path == "/api/facts":
                self._json(200, query_facts(conn, **_facts_query_options(self.path)))
                return
            if path.startswith("/api/facts/"):
                try:
                    self._json(200, get_fact_detail(conn, path.split("/")[3]))
                except LookupError:
                    self._json(404, {"error": "fact not found"})
                return
            if path == "/api/usage/summary":
                query = parse_qs(urlparse(self.path).query)
                self._json(200, get_usage_summary(conn, window=(query.get("window") or ["24h"])[0]))
                return
            if path == "/api/risks/summary":
                query = parse_qs(urlparse(self.path).query)
                self._json(
                    200,
                    get_risk_summary(
                        conn,
                        mode=_query_one(query, "mode", "summary") or "summary",
                        window=_query_one(query, "window", "24h") or "24h",
                    ),
                )
                return
            if path == "/api/validation/minimum-experiment":
                self._json(200, run_minimum_validation_experiment(conn))
                return
            if path == "/api/policy":
                self._json(200, get_effective_policy(conn))
                return
            if path == "/api/audit/recent":
                self._json(200, recent_audit(conn))
                return
            if path == "/api/stories":
                self._json(200, list_stories(conn, **_stories_query_options(self.path)))
                return
            if path.startswith("/api/stories/") and path.endswith("/diagnostics/availability"):
                try:
                    self._json(200, get_diagnostic_availability(conn, path.split("/")[3]))
                except LookupError:
                    self._json(404, {"error": "story not found"})
                return
            if path.startswith("/api/stories/"):
                try:
                    self._json(200, get_story_detail(conn, path.split("/")[3]))
                except LookupError:
                    self._json(404, {"error": "story not found"})
                return
            if path == "/api/client-package/config":
                self._json(200, build_windows_package(conn))
                return
            if path == "/api/client-package/windows":
                package = build_windows_package(conn)
                data = open(package["path"], "rb").read()
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", "attachment; filename=agent-observer-windows.zip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        self._json(404, {"error": "not found"})

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        with connect() as conn:
            if path == "/api/policy":
                try:
                    self._json(200, update_effective_policy(conn, payload))
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path.startswith("/api/collectors/") and path.endswith("/display-name"):
                try:
                    self._json(200, update_collector_display_name(conn, path.split("/")[3], payload.get("display_name", "")))
                except LookupError:
                    self._json(404, {"error": "collector not found"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path.startswith("/api/collectors/") and path.endswith("/raw-upload"):
                try:
                    self._json(200, update_collector_raw_upload(conn, path.split("/")[3], bool(payload.get("enabled"))))
                except LookupError:
                    self._json(404, {"error": "collector not found"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
        self._json(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        with connect() as conn:
            if path.startswith("/api/collectors/"):
                try:
                    self._json(200, delete_collector(conn, path.split("/")[3]))
                except LookupError:
                    self._json(404, {"error": "collector not found"})
                return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        with connect() as conn:
            if path == "/api/collectors/register":
                self._json(200, register_collector(conn, payload))
                return
            if path.startswith("/api/collectors/") and path.endswith("/heartbeat"):
                collector_id = path.split("/")[3]
                self._json(200, heartbeat(conn, collector_id, payload))
                return
            if path == "/api/telemetry/ingest":
                try:
                    self._json(200, ingest_telemetry(conn, payload))
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path == "/api/stories/rebuild":
                self._json(200, rebuild_stories(conn, reason=payload.get("reason", "api")))
                return
            if path == "/api/validation/minimum-experiment":
                self._json(200, run_minimum_validation_experiment(conn))
                return
            if path.startswith("/api/stories/") and path.endswith("/read"):
                try:
                    self._json(200, mark_story_read(conn, path.split("/")[3]))
                except LookupError:
                    self._json(404, {"error": "story not found"})
                return
            if path.startswith("/api/stories/") and path.endswith("/handle"):
                try:
                    self._json(200, handle_story(conn, path.split("/")[3], payload.get("conclusion_code"), payload.get("note")))
                except LookupError:
                    self._json(404, {"error": "story not found"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path.startswith("/api/stories/") and path.endswith("/diagnostics"):
                try:
                    self._json(200, request_diagnostic(conn, path.split("/")[3], payload.get("capability_id", "")))
                except LookupError:
                    self._json(404, {"error": "story not found"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path.startswith("/api/diagnostics/") and path.endswith("/cancel"):
                try:
                    self._json(200, cancel_diagnostic(conn, path.split("/")[3]))
                except LookupError:
                    self._json(404, {"error": "diagnostic job not found"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path.startswith("/api/diagnostics/") and path.endswith("/result"):
                try:
                    self._json(
                        200,
                        record_diagnostic_result(
                            conn,
                            path.split("/")[3],
                            payload.get("status", ""),
                            payload.get("summary", ""),
                            payload.get("projection"),
                        ),
                    )
                except LookupError:
                    self._json(404, {"error": "diagnostic job not found"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path.startswith("/api/collectors/") and "/diagnostics/" in path and path.endswith("/result"):
                parts = path.split("/")
                try:
                    self._json(200, record_collector_diagnostic_result(conn, parts[3], parts[5], payload))
                except LookupError:
                    self._json(404, {"error": "diagnostic job not found"})
                except ValueError as exc:
                    self._json(400, {"error": str(exc)})
                return
        self._json(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
