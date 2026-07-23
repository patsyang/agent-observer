"""OTLP service 测试：覆盖事件提取、数据映射、端到端入库。"""
from __future__ import annotations

from datetime import UTC, datetime

from app.db.connection import connect
from app.otlp.service import (
    _build_api_error_item,
    _build_api_request_item,
    _extract_event_name,
    _flatten_attributes,
    _parse_iso_timestamp,
    process_otlp_logs,
)


def _make_log_record(event_name: str, attrs: dict) -> dict:
    """构造 OTLP log record。"""
    attr_list = []
    for key, value in attrs.items():
        if isinstance(value, bool):
            attr_list.append({"key": key, "value": {"boolValue": value}})
        elif isinstance(value, int):
            attr_list.append({"key": key, "value": {"intValue": str(value)}})
        elif isinstance(value, float):
            attr_list.append({"key": key, "value": {"doubleValue": value}})
        else:
            attr_list.append({"key": key, "value": {"stringValue": str(value)}})
    return {
        "timeUnixNano": "0",
        "observedTimeUnixNano": "1784806254884159500",
        "severityNumber": 9,
        "severityText": "INFO",
        "body": None,
        "attributes": attr_list,
        "droppedAttributesCount": 0,
        "flags": 0,
        "traceId": "",
        "spanId": "",
        "eventName": "event otel\\src\\events\\session_telemetry.rs:843",
    }


def _make_api_request_record(duration_ms="2679", status_code=200) -> dict:
    """构造 codex.api_request log record。"""
    return _make_log_record("codex.api_request", {
        "event.name": "codex.api_request",
        "duration_ms": duration_ms,
        "attempt": 0,
        "http.response.status_code": status_code,
        "endpoint": "/responses",
        "conversation.id": "conv-test-123",
        "event.timestamp": "2026-07-23T11:32:17.075Z",
        "model": "gpt-5.6-terra",
        "auth_mode": "ApiKey",
        "originator": "codex_exec",
    })


def _make_api_error_record(status_code=429, error_message="Rate limit exceeded") -> dict:
    """构造 codex.api_error log record。"""
    return _make_log_record("codex.api_error", {
        "event.name": "codex.api_error",
        "http.response.status_code": status_code,
        "error.message": error_message,
        "conversation.id": "conv-test-123",
        "event.timestamp": "2026-07-23T11:32:17.075Z",
        "model": "gpt-5.6-terra",
    })


def _make_otlp_data(log_records: list[dict]) -> dict:
    """构造完整 OTLP logs JSON。"""
    return {
        "resourceLogs": [{
            "resource": {"attributes": [], "droppedAttributesCount": 0, "entityRefs": []},
            "scopeLogs": [{
                "scope": {"name": "codex_otel.log_only", "version": "", "attributes": []},
                "logRecords": log_records,
            }],
        }],
    }


# ---------- _extract_event_name ----------

def test_extract_event_name_from_attributes():
    """事件名从 attributes["event.name"] 提取，不从顶层 eventName 读。"""
    record = _make_log_record("codex.api_request", {"event.name": "codex.api_request"})
    assert _extract_event_name(record) == "codex.api_request"


def test_extract_event_name_missing_returns_empty():
    record = {"attributes": [], "eventName": "event otel\\src\\foo.rs:123"}
    assert _extract_event_name(record) == ""


# ---------- _flatten_attributes ----------

def test_flatten_attributes_string_value():
    attrs = [{"key": "duration_ms", "value": {"stringValue": "2679"}}]
    assert _flatten_attributes(attrs) == {"duration_ms": "2679"}


def test_flatten_attributes_int_value():
    attrs = [{"key": "attempt", "value": {"intValue": "0"}}]
    assert _flatten_attributes(attrs) == {"attempt": 0}


def test_flatten_attributes_bool_value():
    attrs = [{"key": "success", "value": {"boolValue": True}}]
    assert _flatten_attributes(attrs) == {"success": True}


def test_flatten_attributes_mixed_types():
    attrs = [
        {"key": "duration_ms", "value": {"stringValue": "2679"}},
        {"key": "attempt", "value": {"intValue": "0"}},
        {"key": "success", "value": {"boolValue": True}},
    ]
    result = _flatten_attributes(attrs)
    assert result == {"duration_ms": "2679", "attempt": 0, "success": True}


# ---------- _parse_iso_timestamp ----------

def test_parse_iso_timestamp_with_z_suffix():
    ts = "2026-07-23T11:32:17.075Z"
    result = _parse_iso_timestamp(ts)
    assert result == "2026-07-23T11:32:17+00:00"


def test_parse_iso_timestamp_empty_returns_now():
    result = _parse_iso_timestamp("")
    assert "+00:00" in result


def test_parse_iso_timestamp_invalid_returns_now():
    result = _parse_iso_timestamp("invalid")
    assert "+00:00" in result


# ---------- _build_api_request_item ----------

def test_build_api_request_item_success():
    record = _make_api_request_record(duration_ms="2679", status_code=200)
    item = _build_api_request_item(record)
    assert item is not None
    assert item["fact_type"] == "perf"
    assert item["category"] == "llm_call"
    assert item["source_event_id"] == "otel-conv-test-123-2026-07-23T11:32:17.075Z-0"
    perf = item["perf_signals"][0]
    assert perf["span_type"] == "llm_call"
    assert perf["duration_ms"] == 2679
    assert perf["status"] == "ok"
    assert perf["model"] == "gpt-5.6-terra"
    assert perf["trace_id"] == "conv-test-123"


def test_build_api_request_item_error_status():
    record = _make_api_request_record(duration_ms="1000", status_code=500)
    item = _build_api_request_item(record)
    assert item is not None
    perf = item["perf_signals"][0]
    assert perf["status"] == "error"
    assert perf["error"] == "http_500"
    assert item["severity"] == "medium"


def test_build_api_request_item_missing_duration():
    record = _make_log_record("codex.api_request", {
        "event.name": "codex.api_request",
        "conversation.id": "conv-1",
        "event.timestamp": "2026-07-23T11:32:17.075Z",
    })
    item = _build_api_request_item(record)
    assert item is None


def test_build_api_request_item_missing_conversation_id():
    record = _make_log_record("codex.api_request", {
        "event.name": "codex.api_request",
        "duration_ms": "100",
        "event.timestamp": "2026-07-23T11:32:17.075Z",
    })
    item = _build_api_request_item(record)
    assert item is None


def test_build_api_request_item_string_duration():
    """duration_ms 是 stringValue 类型，需要正确转换。"""
    record = _make_api_request_record(duration_ms="1812", status_code=200)
    item = _build_api_request_item(record)
    assert item is not None
    assert item["perf_signals"][0]["duration_ms"] == 1812


# ---------- _build_api_error_item ----------

def test_build_api_error_item_has_signature_key():
    """P0-1 回归：error_signature 必须含 signature_key。"""
    record = _make_api_error_record(status_code=429, error_message="Rate limit")
    item = _build_api_error_item(record)
    assert item is not None
    assert "error_signature" in item
    assert "signature_key" in item["error_signature"]
    assert item["error_signature"]["category"] == "api_error"
    assert "api_error:http_429:" in item["error_signature"]["signature_key"]


def test_build_api_error_item_severity_5xx():
    record = _make_api_error_record(status_code=500, error_message="Internal error")
    item = _build_api_error_item(record)
    assert item is not None
    assert item["severity"] == "high"


def test_build_api_error_item_severity_4xx():
    record = _make_api_error_record(status_code=429, error_message="Rate limit")
    item = _build_api_error_item(record)
    assert item is not None
    assert item["severity"] == "medium"


# ---------- process_otlp_logs ----------

def test_process_otlp_logs_empty():
    """空 OTLP 数据返回零值。"""
    with connect(":memory:") as conn:
        result = process_otlp_logs(conn, {})
    assert result["accepted"] == 0
    assert result["skipped"] == 0


def test_process_otlp_logs_skips_unknown_event():
    """未知事件被跳过。"""
    record = _make_log_record("codex.sse_event", {
        "event.name": "codex.sse_event",
        "event.kind": "response.created",
    })
    data = _make_otlp_data([record])
    with connect(":memory:") as conn:
        result = process_otlp_logs(conn, data)
    assert result["accepted"] == 0
    assert result["skipped"] == 1


def test_process_otlp_logs_extracts_api_request(tmp_path):
    """端到端：OTLP JSON → process_otlp_logs → perf_signals 有行。"""
    record = _make_api_request_record(duration_ms="2679", status_code=200)
    data = _make_otlp_data([record])
    with connect(tmp_path / "observer.sqlite") as conn:
        result = process_otlp_logs(conn, data)
        conn.commit()
        assert result["accepted"] == 1
        rows = conn.execute("select * from perf_signals where span_type='llm_call'").fetchall()
        assert len(rows) == 1
        assert rows[0]["duration_ms"] == 2679
        assert rows[0]["status"] == "ok"


def test_process_otlp_logs_extracts_api_error(tmp_path):
    """端到端：OTLP JSON → process_otlp_logs → error_signatures 有行。"""
    record = _make_api_error_record(status_code=429, error_message="Rate limit")
    data = _make_otlp_data([record])
    with connect(tmp_path / "observer.sqlite") as conn:
        result = process_otlp_logs(conn, data)
        conn.commit()
        assert result["accepted"] == 1
        rows = conn.execute("select * from error_signatures").fetchall()
        assert len(rows) == 1
        assert "api_error:http_429:" in rows[0]["signature_key"]


def test_process_otlp_logs_mixed_events(tmp_path):
    """端到端：一个 OTLP 请求含 api_request + api_error → 两张表都有数据，无回滚。"""
    api_req = _make_api_request_record(duration_ms="2679", status_code=200)
    api_err = _make_api_error_record(status_code=429, error_message="Rate limit")
    data = _make_otlp_data([api_req, api_err])
    with connect(tmp_path / "observer.sqlite") as conn:
        result = process_otlp_logs(conn, data)
        conn.commit()
        assert result["accepted"] == 2
        perf_rows = conn.execute("select * from perf_signals where span_type='llm_call'").fetchall()
        err_rows = conn.execute("select * from error_signatures").fetchall()
        assert len(perf_rows) == 1
        assert len(err_rows) == 1


def test_process_otlp_logs_dedup(tmp_path):
    """端到端：同一 OTLP JSON 重复发送 → 行数不翻倍。"""
    record = _make_api_request_record(duration_ms="2679", status_code=200)
    data = _make_otlp_data([record])
    with connect(tmp_path / "observer.sqlite") as conn:
        result1 = process_otlp_logs(conn, data)
        conn.commit()
        result2 = process_otlp_logs(conn, data)
        conn.commit()
        assert result1["accepted"] == 1
        assert result2["accepted"] == 0
        assert result2["duplicates"] == 1
        rows = conn.execute("select * from perf_signals where span_type='llm_call'").fetchall()
        assert len(rows) == 1
