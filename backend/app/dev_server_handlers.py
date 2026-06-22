from __future__ import annotations

import json
import sqlite3
from urllib.parse import parse_qs, unquote, urlparse

from app.collectors.service import (
    delete_collector,
    heartbeat,
    list_collectors,
    register_collector,
    update_collector_display_name,
)
from app.conversations.service import get_conversation_for_fact, get_conversation_query, query_conversations
from app.dashboard.service import get_dashboard_summary
from app.db.connection import connect
from app.evidence_enrichment.service import (
    cancel_enrichment,
    get_enrichment_availability,
    get_next_collector_enrichment,
    record_collector_enrichment_result,
    record_enrichment_result,
    request_enrichment,
)
from app.ingest.service import ingest_telemetry
from app.package.builder import build_windows_package
from app.policy import get_effective_policy, recent_audit, update_effective_policy
from app.risks.service import get_risk_summary
from app.behavior_signals.service import get_signal_detail, handle_signal, list_signals, mark_signal_read, rebuild_signals
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


def _signals_query_options(raw_path: str) -> dict:
    query = parse_qs(urlparse(raw_path).query)
    return {
        "window": _query_one(query, "window", "all"),
        "page": _query_int(query, "page", 1),
        "page_size": _query_int(query, "page_size", 20),
    }


def _conversations_query_options(raw_path: str) -> dict:
    query = parse_qs(urlparse(raw_path).query)
    return {
        "window": _query_one(query, "window", "1h") or "1h",
        "start_at": _query_one(query, "start_at"),
        "end_at": _query_one(query, "end_at"),
        "prompt_query": _query_one(query, "prompt_query"),
        "response_query": _query_one(query, "response_query"),
        "page": _query_int(query, "page", 1),
        "page_size": _query_int(query, "page_size", 50),
    }


def _path_part(path: str, index: int) -> str:
    return unquote(path.split("/")[index])


def handle_get(handler) -> None:
    path = urlparse(handler.path).path
    try:
        with connect() as conn:
            if path == "/api/collectors":
                return handler._json(200, {"collectors": list_collectors(conn)})
            if path == "/api/dashboard/summary":
                query = parse_qs(urlparse(handler.path).query)
                return handler._json(200, get_dashboard_summary(conn, window=_query_one(query, "window", "1h") or "1h"))
            if path.startswith("/api/collectors/") and path.endswith("/enrichments/next"):
                try:
                    return handler._json(200, get_next_collector_enrichment(conn, path.split("/")[3]))
                except LookupError:
                    return handler._json(404, {"error": "collector not found"})
            if path == "/api/conversations":
                return handler._json(200, query_conversations(conn, **_conversations_query_options(handler.path)))
            if path.startswith("/api/conversations/by-fact/"):
                try:
                    return handler._json(200, get_conversation_for_fact(conn, _path_part(path, 4)))
                except LookupError:
                    return handler._json(404, {"error": "conversation not found"})
            if path.startswith("/api/conversations/"):
                try:
                    return handler._json(200, get_conversation_query(conn, _path_part(path, 3)))
                except LookupError:
                    return handler._json(404, {"error": "conversation not found"})
            if path == "/api/usage/summary":
                query = parse_qs(urlparse(handler.path).query)
                return handler._json(200, get_usage_summary(conn, window=(query.get("window") or ["24h"])[0]))
            if path == "/api/risks/summary":
                query = parse_qs(urlparse(handler.path).query)
                return handler._json(200, get_risk_summary(conn, mode=_query_one(query, "mode", "summary") or "summary", window=_query_one(query, "window", "24h") or "24h"))
            if path == "/api/validation/minimum-experiment":
                return handler._json(200, run_minimum_validation_experiment(conn))
            if path == "/api/policy":
                return handler._json(200, get_effective_policy(conn))
            if path == "/api/audit/recent":
                return handler._json(200, recent_audit(conn))
            if path == "/api/signals":
                return handler._json(200, list_signals(conn, **_signals_query_options(handler.path)))
            if path.startswith("/api/signals/") and path.endswith("/enrichments/availability"):
                try:
                    return handler._json(200, get_enrichment_availability(conn, path.split("/")[3]))
                except LookupError:
                    return handler._json(404, {"error": "signal not found"})
            if path.startswith("/api/signals/"):
                try:
                    return handler._json(200, get_signal_detail(conn, path.split("/")[3]))
                except LookupError:
                    return handler._json(404, {"error": "signal not found"})
            if path == "/api/client-package/config":
                return handler._json(200, build_windows_package(conn))
            if path == "/api/client-package/windows":
                package = build_windows_package(conn)
                return _send_package(handler, package["path"])
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            return handler._json(503, {"error": "database busy", "reason_code": "sqlite_busy"})
        raise
    handler._json(404, {"error": "not found"})


def handle_patch(handler) -> None:
    path = urlparse(handler.path).path
    payload = _read_payload(handler)
    with connect() as conn:
        if path == "/api/policy":
            try:
                return handler._json(200, update_effective_policy(conn, payload))
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
        if path.startswith("/api/collectors/") and path.endswith("/display-name"):
            try:
                return handler._json(200, update_collector_display_name(conn, path.split("/")[3], payload.get("display_name", "")))
            except LookupError:
                return handler._json(404, {"error": "collector not found"})
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
    handler._json(404, {"error": "not found"})


def handle_delete(handler) -> None:
    path = urlparse(handler.path).path
    with connect() as conn:
        if path.startswith("/api/collectors/"):
            try:
                return handler._json(200, delete_collector(conn, path.split("/")[3]))
            except LookupError:
                return handler._json(404, {"error": "collector not found"})
    handler._json(404, {"error": "not found"})


def handle_post(handler) -> None:
    path = urlparse(handler.path).path
    payload = _read_payload(handler)
    try:
        with connect() as conn:
            return _handle_post_locked(handler, conn, path, payload)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            return handler._json(503, {"error": "database busy", "reason_code": "sqlite_busy"})
        raise
    handler._json(404, {"error": "not found"})


def _handle_post_locked(handler, conn, path: str, payload: dict) -> None:
        if path == "/api/collectors/register":
            try:
                return handler._json(200, register_collector(conn, payload))
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
        if path.startswith("/api/collectors/") and path.endswith("/heartbeat"):
            try:
                return handler._json(200, heartbeat(conn, path.split("/")[3], payload))
            except LookupError:
                return handler._json(404, {"error": "collector not found"})
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
        if path == "/api/telemetry/ingest":
            try:
                return handler._json(200, ingest_telemetry(conn, payload))
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
        if path == "/api/signals/rebuild":
            return handler._json(200, rebuild_signals(conn, reason=payload.get("reason", "api")))
        if path == "/api/validation/minimum-experiment":
            return handler._json(200, run_minimum_validation_experiment(conn))
        if path.startswith("/api/signals/") and path.endswith("/read"):
            try:
                return handler._json(200, mark_signal_read(conn, path.split("/")[3]))
            except LookupError:
                return handler._json(404, {"error": "signal not found"})
        if path.startswith("/api/signals/") and path.endswith("/handle"):
            try:
                return handler._json(200, handle_signal(conn, path.split("/")[3], payload.get("conclusion_code"), payload.get("note")))
            except LookupError:
                return handler._json(404, {"error": "signal not found"})
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
        if path.startswith("/api/signals/") and path.endswith("/enrichments"):
            try:
                return handler._json(200, request_enrichment(conn, path.split("/")[3], payload.get("capability_id", "")))
            except LookupError:
                return handler._json(404, {"error": "signal not found"})
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
        if path.startswith("/api/enrichments/") and path.endswith("/cancel"):
            try:
                return handler._json(200, cancel_enrichment(conn, path.split("/")[3]))
            except LookupError:
                return handler._json(404, {"error": "enrichment job not found"})
            except ValueError as exc:
                return handler._json(400, {"error": str(exc)})
        if path.startswith("/api/enrichments/") and path.endswith("/result"):
            return _handle_enrichment_result(handler, conn, path, payload)
        if path.startswith("/api/collectors/") and "/enrichments/" in path and path.endswith("/result"):
            return _handle_collector_enrichment_result(handler, conn, path, payload)
        handler._json(404, {"error": "not found"})


def _handle_enrichment_result(handler, conn, path: str, payload: dict) -> None:
    try:
        return handler._json(
            200,
            record_enrichment_result(
                conn,
                path.split("/")[3],
                payload.get("status", ""),
                payload.get("summary", ""),
                payload.get("projection"),
                payload.get("redaction"),
            ),
        )
    except LookupError:
        return handler._json(404, {"error": "enrichment job not found"})
    except ValueError as exc:
        return handler._json(400, {"error": str(exc)})


def _handle_collector_enrichment_result(handler, conn, path: str, payload: dict) -> None:
    parts = path.split("/")
    try:
        return handler._json(200, record_collector_enrichment_result(conn, parts[3], parts[5], payload))
    except LookupError:
        return handler._json(404, {"error": "enrichment job not found"})
    except ValueError as exc:
        return handler._json(400, {"error": str(exc)})


def _read_payload(handler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    return json.loads(handler.rfile.read(length) or b"{}")


def _send_package(handler, package_path: str) -> None:
    data = open(package_path, "rb").read()
    handler.send_response(200)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Type", "application/zip")
    handler.send_header("Content-Disposition", "attachment; filename=agent-observer-windows.zip")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
