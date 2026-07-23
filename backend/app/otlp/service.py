"""OTLP logs → agent-observer batch dict 翻译。

基于真实数据验证（2026-07-23，codex v0.144.1）：
- Content-Type: application/json，无 gzip
- eventName 顶层是代码位置，事件名在 attributes["event.name"]
- duration 字段名是 duration_ms，值是 stringValue 类型
- traceId/spanId 都是空字符串，用 conversation.id + event.timestamp 构造唯一 ID
- timeUnixNano 是 "0"，实际时间在 attributes["event.timestamp"]（ISO 格式）
- api_request 无 success 字段，用 http.response.status_code 判断状态
"""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from app.collector_client.version import COLLECTOR_PROTOCOL_VERSION
from app.ingest.service import ingest_telemetry

logger = logging.getLogger(__name__)

_OTLP_COLLECTOR_ID = "otlp-receiver"
_OTLP_SOURCE_ID = "codex-otel"
_OTLP_AGENT_TYPE = "codex"
_OTLP_SOURCE_KIND = "codex_otel"
_OTLP_AGENT_VERSION = "codex-otel-0.1"


def process_otlp_logs(conn, data: dict) -> dict:
    """处理 OTLP logs，提取 codex 事件写入数据库。

    处理 2 个事件：
    - codex.api_request → perf_signals (span_type='llm_call')
    - codex.api_error → observed_facts (fact_type='error') + error_signatures
    """
    items = []
    skipped = 0

    for resource_logs in data.get("resourceLogs", []):
        for scope_logs in resource_logs.get("scopeLogs", []):
            for log_record in scope_logs.get("logRecords", []):
                event_name = _extract_event_name(log_record)
                item = _dispatch_event(event_name, log_record)
                if item:
                    items.append(item)
                else:
                    skipped += 1

    if not items and skipped > 0:
        logger.info("OTLP logs 收到 %d 条但全部跳过", skipped)

    if not items:
        return {"accepted": 0, "duplicates": 0, "skipped": skipped}

    batch = _wrap_batch(items)
    result = ingest_telemetry(conn, batch)
    accepted = result.get("accepted", 0)
    if accepted > 0:
        logger.info("OTLP 入库: accepted=%d, duplicates=%d, skipped=%d",
                    accepted, result.get("duplicates", 0), skipped)
    return {
        "accepted": accepted,
        "duplicates": result.get("duplicates", 0),
        "skipped": skipped,
    }


def _extract_event_name(log_record: dict) -> str:
    """从 attributes["event.name"] 提取事件名。

    注意：顶层 eventName 字段是代码位置（如 "event otel\\src\\..."），不是事件名。
    """
    for attr in log_record.get("attributes", []):
        if attr.get("key") == "event.name":
            return attr.get("value", {}).get("stringValue", "")
    return ""


def _dispatch_event(event_name: str, log_record: dict) -> dict | None:
    """根据事件名分发到对应处理器。"""
    if event_name == "codex.api_request":
        return _build_api_request_item(log_record)
    if event_name == "codex.api_error":
        return _build_api_error_item(log_record)
    return None


# ---------- 事件处理器 ----------

def _build_api_request_item(log_record: dict) -> dict | None:
    """codex.api_request → perf_signals (span_type='llm_call')。"""
    attrs = _flatten_attributes(log_record.get("attributes", []))
    duration_ms = attrs.get("duration_ms")
    if duration_ms is None:
        return None

    conversation_id = attrs.get("conversation.id", "")
    event_timestamp = attrs.get("event.timestamp", "")
    if not conversation_id or not event_timestamp:
        return None

    # traceId/spanId 都是空字符串，用 conversation.id + event.timestamp + attempt 构造唯一 ID
    # attempt 纳入 ID 防止同毫秒重试被错误去重（P1-1）
    try:
        attempt_val = int(attrs.get("attempt", 0))
    except (ValueError, TypeError):
        attempt_val = 0
    trace_id = conversation_id
    span_id = f"api-{event_timestamp}-{attempt_val}"
    source_event_id = f"otel-{conversation_id}-{event_timestamp}-{attempt_val}"

    # duration_ms 是 stringValue，需要转 int
    try:
        duration_val = int(float(str(duration_ms)))
    except (ValueError, TypeError):
        return None

    http_status = attrs.get("http.response.status_code", 200)
    try:
        status_code = int(http_status)
    except (ValueError, TypeError):
        status_code = 200
    success = 200 <= status_code < 400

    model = attrs.get("model", "")
    occurred_at = _parse_iso_timestamp(event_timestamp)

    perf_signal = {
        "trace_id": trace_id,
        "span_id": span_id,
        "span_type": "llm_call",
        "span_name": "codex.api_request",
        "duration_ms": duration_val,
        "ttft_ms": 0,
        "tps": 0.0,
        "status": "ok" if success else "error",
        "error": "" if success else f"http_{status_code}",
        "model": model,
        "tool_name": "",
        "occurred_at": occurred_at,
    }

    return {
        "source_event_id": source_event_id,
        "fact_type": "perf",
        "category": "llm_call",
        "quality": "high",
        "severity": "low" if success else "medium",
        "summary": f"LLM API 调用 ({model}, {duration_val}ms, HTTP {status_code})",
        "occurred_at": occurred_at,
        "raw_hash": hashlib.sha256(source_event_id.encode("utf-8")).hexdigest(),
        "span": f"codex-otel:{conversation_id[:12]}",
        "source_refs": {
            "conversation_ref": conversation_id,
            "session_ref": conversation_id,
        },
        "source_specific": {
            "source_template": "codex.otel.logs.v1",
            "http_status": status_code,
            "endpoint": attrs.get("endpoint", ""),
            "attempt": attrs.get("attempt", 0),
        },
        "perf_signals": [perf_signal],
    }


def _build_api_error_item(log_record: dict) -> dict | None:
    """codex.api_error → observed_facts (fact_type='error') + error_signatures。

    P0-1 修复：error_signature 必须含 signature_key（ingest 强制下标取值）。
    """
    attrs = _flatten_attributes(log_record.get("attributes", []))
    http_status = attrs.get("http.response.status_code", 0)
    try:
        status_code = int(http_status)
    except (ValueError, TypeError):
        status_code = 0

    error_message = attrs.get("error.message", "") or attrs.get("error_message", "")
    conversation_id = attrs.get("conversation.id", "")
    event_timestamp = attrs.get("event.timestamp", "")
    if not event_timestamp:
        return None

    occurred_at = _parse_iso_timestamp(event_timestamp)
    source_event_id = f"otel-err-{conversation_id}-{event_timestamp}"

    # P0-1: signature_key 是必需字段
    msg_hash = hashlib.sha256(error_message.encode("utf-8")).hexdigest()[:12] if error_message else "no_msg"
    signature_key = f"api_error:http_{status_code}:{msg_hash}"

    return {
        "source_event_id": source_event_id,
        "fact_type": "error",
        "category": "api_error",
        "quality": "high",
        "severity": "high" if status_code >= 500 else "medium",
        "summary": f"API 错误 HTTP {status_code}: {error_message[:200]}",
        "occurred_at": occurred_at,
        "raw_hash": hashlib.sha256(source_event_id.encode("utf-8")).hexdigest(),
        "span": f"codex-otel-err:{conversation_id[:12]}",
        "source_refs": {
            "conversation_ref": conversation_id,
            "session_ref": conversation_id,
        },
        "source_specific": {
            "source_template": "codex.otel.logs.v1",
            "http_status": status_code,
            "error_message": error_message[:500],
        },
        "error_signature": {
            "signature_key": signature_key,
            "category": "api_error",
        },
    }


# ---------- 工具函数 ----------

def _flatten_attributes(attrs: list) -> dict:
    """把 OTLP attributes 列表展平为 dict。

    注意：所有值都保留为原始类型（stringValue → str, intValue → int, 等）。
    duration_ms 等字段是 stringValue 类型，需要调用方自行转换。
    """
    result = {}
    for attr in attrs:
        key = attr.get("key")
        if not key:
            continue
        value = attr.get("value", {})
        # OTLP AnyValue 只设一个类型字段，按 stringValue > intValue > doubleValue > boolValue 优先级取
        if "stringValue" in value:
            result[key] = value["stringValue"]
        elif "intValue" in value:
            try:
                result[key] = int(value["intValue"])
            except (ValueError, TypeError):
                result[key] = value["intValue"]
        elif "doubleValue" in value:
            result[key] = float(value["doubleValue"])
        elif "boolValue" in value:
            result[key] = value["boolValue"]
    return result


def _parse_iso_timestamp(ts: str) -> str:
    """解析 ISO 格式时间戳（如 '2026-07-23T11:32:17.075Z'）。

    codex OTLP 的 event.timestamp 是 ISO 格式字符串，直接规范化返回。
    """
    if not ts:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
    try:
        # 处理 Z 后缀
        normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.replace(microsecond=0).isoformat()
    except (ValueError, TypeError):
        logger.warning("无法解析时间戳: %s", ts)
        return datetime.now(UTC).replace(microsecond=0).isoformat()


def _wrap_batch(items: list[dict]) -> dict:
    return {
        "batch_id": f"otlp-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
        "collector_id": _OTLP_COLLECTOR_ID,
        "source_id": _OTLP_SOURCE_ID,
        "source": _OTLP_AGENT_TYPE,
        "agent_type": _OTLP_AGENT_TYPE,
        "source_kind": _OTLP_SOURCE_KIND,
        "protocol_version": COLLECTOR_PROTOCOL_VERSION,
        "agent_version": _OTLP_AGENT_VERSION,
        "items": items,
    }
