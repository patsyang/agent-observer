"""OTLP service 测试：覆盖事件提取、数据映射、端到端入库。"""
from __future__ import annotations

from datetime import UTC, datetime

from app.db.connection import connect
from app.otlp.service import (
    _build_api_error_item,
    _build_api_request_item,
    _extract_event_name,
    _flatten_attributes,
    _handle_sse_event,
    _iso_minus_minutes,
    _parse_iso_timestamp,
    _safe_int,
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


def _make_sse_event_record(
    event_kind="response.completed",
    output_tokens=150,
    conversation_id="conv-test-123",
    event_timestamp="2026-07-23T11:32:20.000Z",
) -> dict:
    """构造 codex.sse_event log record。"""
    return _make_log_record("codex.sse_event", {
        "event.name": "codex.sse_event",
        "event.kind": event_kind,
        "output_token_count": output_tokens,
        "input_token_count": 500,
        "conversation.id": conversation_id,
        "event.timestamp": event_timestamp,
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


# ---------- _safe_int / _iso_minus_minutes ----------

def test_safe_int_valid():
    assert _safe_int("123") == 123
    assert _safe_int(123) == 123
    assert _safe_int(0) == 0


def test_safe_int_invalid():
    assert _safe_int(None) == 0
    assert _safe_int("abc") == 0
    assert _safe_int("") == 0


def test_iso_minus_minutes_normal():
    result = _iso_minus_minutes("2026-07-23T11:32:20+00:00", 10)
    assert result == "2026-07-23T11:22:20+00:00"


def test_iso_minus_minutes_with_z_suffix():
    result = _iso_minus_minutes("2026-07-23T11:32:20Z", 10)
    assert result == "2026-07-23T11:22:20+00:00"


def test_iso_minus_minutes_invalid_returns_now():
    result = _iso_minus_minutes("invalid", 10)
    assert "+00:00" in result


# ---------- _handle_sse_event ----------

def test_handle_sse_event_updates_tps(tmp_path):
    """正常更新：api_request 先入库，sse_event 更新 tps。"""
    api_req = _make_api_request_record(duration_ms="3000", status_code=200)
    sse = _make_sse_event_record(output_tokens=150, event_timestamp="2026-07-23T11:32:20.000Z")
    # api_request 的 timestamp 是 2026-07-23T11:32:17.075Z
    with connect(tmp_path / "observer.sqlite") as conn:
        process_otlp_logs(conn, _make_otlp_data([api_req]))
        conn.commit()
        result = _handle_sse_event(conn, sse)
        assert result["tps_updated"] == 1
        row = conn.execute("select tps from perf_signals where span_type='llm_call'").fetchone()
        # TPS = 150 / (3000/1000) = 50.0
        assert row["tps"] == 50.0


def test_handle_sse_event_skips_non_completed(tmp_path):
    """跳过非 response.completed 的 sse_event。"""
    sse = _make_sse_event_record(event_kind="response.output_text.delta")
    with connect(":memory:") as conn:
        result = _handle_sse_event(conn, sse)
    assert result["tps_updated"] == 0
    assert result["skipped"] == 1


def test_handle_sse_event_skips_zero_tokens(tmp_path):
    """跳过 output_token_count=0 的 sse_event。"""
    sse = _make_sse_event_record(output_tokens=0)
    with connect(":memory:") as conn:
        result = _handle_sse_event(conn, sse)
    assert result["tps_updated"] == 0
    assert result["skipped"] == 1


def test_handle_sse_event_no_matching_perf_signal(tmp_path):
    """未找到 api_request perf_signal 时不更新。"""
    sse = _make_sse_event_record(output_tokens=150)
    with connect(tmp_path / "observer.sqlite") as conn:
        result = _handle_sse_event(conn, sse)
    assert result["tps_updated"] == 0


def test_handle_sse_event_zero_duration_skipped(tmp_path):
    """duration_ms=0 的 api_request 不更新 tps。"""
    api_req = _make_api_request_record(duration_ms="0", status_code=200)
    sse = _make_sse_event_record(output_tokens=150, event_timestamp="2026-07-23T11:32:20.000Z")
    with connect(tmp_path / "observer.sqlite") as conn:
        process_otlp_logs(conn, _make_otlp_data([api_req]))
        conn.commit()
        result = _handle_sse_event(conn, sse)
    assert result["tps_updated"] == 0


def test_handle_sse_event_time_window_expired(tmp_path):
    """P1-2: api_request 超过 10 分钟窗口不匹配。"""
    # api_request 在 11:00:00
    api_req = _make_log_record("codex.api_request", {
        "event.name": "codex.api_request",
        "duration_ms": "3000",
        "attempt": 0,
        "http.response.status_code": 200,
        "endpoint": "/responses",
        "conversation.id": "conv-test-123",
        "event.timestamp": "2026-07-23T11:00:00.000Z",
        "model": "gpt-5.6-terra",
        "auth_mode": "ApiKey",
        "originator": "codex_exec",
    })
    # sse_event 在 11:15:00（超过 10 分钟窗口）
    sse = _make_sse_event_record(output_tokens=150, event_timestamp="2026-07-23T11:15:00.000Z")
    with connect(tmp_path / "observer.sqlite") as conn:
        process_otlp_logs(conn, _make_otlp_data([api_req]))
        conn.commit()
        result = _handle_sse_event(conn, sse)
    assert result["tps_updated"] == 0


def test_handle_sse_event_tps_too_large_skipped(tmp_path):
    """P2-1: TPS > 1000 置 0 不更新。"""
    # duration_ms=1ms, output_tokens=2000 → TPS=2000000 > 1000
    api_req = _make_api_request_record(duration_ms="1", status_code=200)
    sse = _make_sse_event_record(output_tokens=2000, event_timestamp="2026-07-23T11:32:20.000Z")
    with connect(tmp_path / "observer.sqlite") as conn:
        process_otlp_logs(conn, _make_otlp_data([api_req]))
        conn.commit()
        result = _handle_sse_event(conn, sse)
    assert result["tps_updated"] == 0
    row = conn.execute("select tps from perf_signals where span_type='llm_call'").fetchone()
    assert row["tps"] == 0.0


# ---------- process_otlp_logs（sse_event 端到端） ----------

def test_process_otlp_logs_sse_event_does_not_create_usage(tmp_path):
    """防翻倍：sse_event 不写 usage_signal。"""
    api_req = _make_api_request_record(duration_ms="3000", status_code=200)
    sse = _make_sse_event_record(output_tokens=150, event_timestamp="2026-07-23T11:32:20.000Z")
    data = _make_otlp_data([api_req, sse])
    with connect(tmp_path / "observer.sqlite") as conn:
        process_otlp_logs(conn, data)
        conn.commit()
        usage_rows = conn.execute("select * from usage_signals").fetchall()
        assert len(usage_rows) == 0


def test_process_otlp_logs_mixed_api_request_and_sse(tmp_path):
    """P1-1 端到端：同批 logs 中 sse_event 排在 api_request 之前，两阶段处理确保 tps 被更新。"""
    # sse_event 在 logRecords 中排在 api_request 之前
    sse = _make_sse_event_record(output_tokens=300, event_timestamp="2026-07-23T11:32:20.000Z")
    api_req = _make_api_request_record(duration_ms="6000", status_code=200)
    data = _make_otlp_data([sse, api_req])  # sse 在前
    with connect(tmp_path / "observer.sqlite") as conn:
        result = process_otlp_logs(conn, data)
        conn.commit()
        assert result["accepted"] == 1
        assert result["tps_updated"] == 1
        row = conn.execute("select tps from perf_signals where span_type='llm_call'").fetchone()
        # TPS = 300 / (6000/1000) = 50.0
        assert row["tps"] == 50.0


def test_process_otlp_logs_sse_before_api_request(tmp_path):
    """sse_event 先于 api_request 到达（跨批），不报错不更新。"""
    sse = _make_sse_event_record(output_tokens=150, event_timestamp="2026-07-23T11:32:20.000Z")
    with connect(tmp_path / "observer.sqlite") as conn:
        result = process_otlp_logs(conn, _make_otlp_data([sse]))
        conn.commit()
        assert result["tps_updated"] == 0
        assert result["accepted"] == 0


def test_process_otlp_logs_multi_turn_association(tmp_path):
    """多轮对话关联：第 N 轮 sse_event 匹配第 N 轮 api_request。"""
    # 第 1 轮：api_request 在 11:00:00, sse_event 在 11:00:03
    api1 = _make_log_record("codex.api_request", {
        "event.name": "codex.api_request",
        "duration_ms": "2000",
        "attempt": 0,
        "http.response.status_code": 200,
        "endpoint": "/responses",
        "conversation.id": "conv-multi",
        "event.timestamp": "2026-07-23T11:00:00.000Z",
        "model": "gpt-5.6-terra",
        "auth_mode": "ApiKey",
        "originator": "codex_exec",
    })
    sse1 = _make_sse_event_record(output_tokens=100, conversation_id="conv-multi",
                                  event_timestamp="2026-07-23T11:00:03.000Z")
    # 第 2 轮：api_request 在 11:05:00, sse_event 在 11:05:04
    api2 = _make_log_record("codex.api_request", {
        "event.name": "codex.api_request",
        "duration_ms": "4000",
        "attempt": 0,
        "http.response.status_code": 200,
        "endpoint": "/responses",
        "conversation.id": "conv-multi",
        "event.timestamp": "2026-07-23T11:05:00.000Z",
        "model": "gpt-5.6-terra",
        "auth_mode": "ApiKey",
        "originator": "codex_exec",
    })
    sse2 = _make_sse_event_record(output_tokens=200, conversation_id="conv-multi",
                                  event_timestamp="2026-07-23T11:05:04.000Z")
    with connect(tmp_path / "observer.sqlite") as conn:
        # 第 1 轮
        process_otlp_logs(conn, _make_otlp_data([api1, sse1]))
        conn.commit()
        # 第 2 轮
        process_otlp_logs(conn, _make_otlp_data([api2, sse2]))
        conn.commit()
        rows = conn.execute(
            "select duration_ms, tps from perf_signals where span_type='llm_call' order by occurred_at"
        ).fetchall()
        assert len(rows) == 2
        # 第 1 轮：TPS = 100 / (2000/1000) = 50.0
        assert rows[0]["duration_ms"] == 2000
        assert rows[0]["tps"] == 50.0
        # 第 2 轮：TPS = 200 / (4000/1000) = 50.0
        assert rows[1]["duration_ms"] == 4000
        assert rows[1]["tps"] == 50.0


def test_process_otlp_logs_sse_event_commit_persisted(tmp_path):
    """P1-3: 只有 sse_event 时 UPDATE 被显式 commit 持久化。"""
    db_path = tmp_path / "observer.sqlite"
    # 先入库一个 api_request
    api_req = _make_api_request_record(duration_ms="3000", status_code=200)
    with connect(db_path) as conn:
        process_otlp_logs(conn, _make_otlp_data([api_req]))
        conn.commit()
    # 只发 sse_event
    sse = _make_sse_event_record(output_tokens=150, event_timestamp="2026-07-23T11:32:20.000Z")
    with connect(db_path) as conn:
        result = process_otlp_logs(conn, _make_otlp_data([sse]))
        # process_otlp_logs 内部 commit（tps_updated > 0）
    assert result["tps_updated"] == 1
    # 用独立连接查询，确认被持久化
    with connect(db_path) as conn:
        row = conn.execute("select tps from perf_signals where span_type='llm_call'").fetchone()
        assert row["tps"] == 50.0
