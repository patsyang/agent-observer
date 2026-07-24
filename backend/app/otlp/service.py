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
from datetime import UTC, datetime, timedelta

from app.collector_client.version import COLLECTOR_PROTOCOL_VERSION
from app.ingest.service import ingest_telemetry

logger = logging.getLogger(__name__)

_OTLP_COLLECTOR_ID = "otlp-receiver"
_OTLP_SOURCE_ID = "codex-otel"
_OTLP_AGENT_TYPE = "codex"
_OTLP_SOURCE_KIND = "codex_otel"
_OTLP_AGENT_VERSION = "codex-otel-0.1"
_TPS_MAX_REASONABLE = 1000.0  # GPT-4o 峰值约 100 tps，1000 是保守上限（P2-1）


def process_otlp_logs(conn, data: dict) -> dict:
    """处理 OTLP logs，提取 codex 事件写入数据库。

    处理 3 个事件：
    - codex.api_request → perf_signals (span_type='llm_call')
    - codex.api_error → observed_facts (fact_type='error') + error_signatures
    - codex.sse_event (response.completed) → UPDATE perf_signal.tps（不走 ingest）

    P1-1: 两阶段处理。第一遍收集 items + sse_events，第二遍先 ingest api_request
    再处理 sse_event，防止同批乱序导致 sse_event 找不到 api_request。
    """
    items = []
    sse_events = []
    skipped = 0

    for resource_logs in data.get("resourceLogs", []):
        for scope_logs in resource_logs.get("scopeLogs", []):
            for log_record in scope_logs.get("logRecords", []):
                event_name = _extract_event_name(log_record)
                if event_name == "codex.sse_event":
                    sse_events.append(log_record)
                    continue
                item = _dispatch_event(event_name, log_record)
                if item:
                    items.append(item)
                else:
                    skipped += 1

    # 第二阶段 1：先 ingest api_request + api_error，确保 perf_signal 入库
    accepted = 0
    duplicates = 0
    if items:
        batch = _wrap_batch(items)
        result = ingest_telemetry(conn, batch)
        accepted = result.get("accepted", 0)
        duplicates = result.get("duplicates", 0)
        if accepted > 0:
            logger.info("OTLP 入库: accepted=%d, duplicates=%d, skipped=%d",
                        accepted, duplicates, skipped)

    # 第二阶段 2：api_request 入库后，再处理 sse_event 做 SELECT + UPDATE
    tps_updated = 0
    for sse_record in sse_events:
        try:
            result = _handle_sse_event(conn, sse_record)
            tps_updated += result["tps_updated"]
            skipped += result["skipped"]
        except Exception:
            logger.exception("sse_event 处理失败，跳过该条")
            skipped += 1

    # P2-3: sse_event 全部未匹配时输出 warning，避免静默失败
    if sse_events and tps_updated == 0:
        logger.warning("OTLP 收到 %d 条 sse_event 但 TPS 全部未更新", len(sse_events))

    # P1-3: 显式 commit，消除对 write_lock 隐性行为的依赖
    if tps_updated > 0:
        conn.commit()

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "skipped": skipped,
        "tps_updated": tps_updated,
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


# ---------- sse_event 处理（TPS 计算） ----------

def _handle_sse_event(conn, log_record: dict) -> dict:
    """处理 codex.sse_event (response.completed)，更新最近 api_request 的 tps。

    不写新的 fact/usage_signal，只 UPDATE 已有 perf_signal.tps。
    """
    attrs = _flatten_attributes(log_record.get("attributes", []))
    event_kind = str(attrs.get("event.kind", ""))

    # 只处理 response.completed（携带 token counts）
    if event_kind != "response.completed":
        return {"skipped": 1, "tps_updated": 0}

    output_token_count = _safe_int(attrs.get("output_token_count"))
    if output_token_count <= 0:
        return {"skipped": 1, "tps_updated": 0}

    conversation_id = attrs.get("conversation.id", "")
    event_timestamp = attrs.get("event.timestamp", "")
    if not conversation_id or not event_timestamp:
        return {"skipped": 1, "tps_updated": 0}

    occurred_at = _parse_iso_timestamp(event_timestamp)
    # P1-2: 时间窗口下界 10 分钟，避免匹配到很久之前的 api_request
    time_floor = _iso_minus_minutes(occurred_at, 10)

    # 查找同一 conversation 最近的 api_request llm_call span
    # P1-2: 加 occurred_at >= ? 下界与方案 2.3 节设计对齐
    row = conn.execute(
        """
        select signal_id, duration_ms from perf_signals
        where conversation_ref = ?
          and span_type = 'llm_call'
          and occurred_at <= ?
          and occurred_at >= ?
          and duration_ms > 0
        order by occurred_at desc
        limit 1
        """,
        (conversation_id, occurred_at, time_floor),
    ).fetchone()

    if not row:
        logger.debug("sse_event: 未找到 conversation=%s 的 api_request perf_signal", conversation_id[:16])
        return {"skipped": 0, "tps_updated": 0}

    duration_ms = int(row["duration_ms"])
    if duration_ms <= 0:
        return {"skipped": 0, "tps_updated": 0}

    tps = round(output_token_count / (duration_ms / 1000.0), 2)
    # P2-1: TPS 异常大值校验，防止 duration_ms 单位错误或 token 字段误填
    if tps > _TPS_MAX_REASONABLE:
        logger.warning("sse_event TPS 异常: tps=%.2f > %.0f, conv=%s, tokens=%d, duration=%dms, 置 0",
                       tps, _TPS_MAX_REASONABLE, conversation_id[:16], output_token_count, duration_ms)
        return {"skipped": 0, "tps_updated": 0}

    conn.execute(
        "update perf_signals set tps = ? where signal_id = ?",
        (tps, row["signal_id"]),
    )
    logger.info("sse_event TPS 更新: conv=%s, tokens=%d, duration=%dms, tps=%.2f",
                conversation_id[:16], output_token_count, duration_ms, tps)
    return {"skipped": 0, "tps_updated": 1}


def _safe_int(value) -> int:
    """安全转 int，兼容 intValue/stringValue/float 字符串（与 duration_ms 转换一致）。"""
    try:
        return int(float(str(value)))
    except (ValueError, TypeError):
        return 0


def _iso_minus_minutes(iso_str: str, minutes: int) -> str:
    """ISO 时间字符串减去指定分钟数，返回 ISO 字符串（P1-2 时间窗口下界）。"""
    try:
        normalized = iso_str.replace("Z", "+00:00") if iso_str.endswith("Z") else iso_str
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (dt - timedelta(minutes=minutes)).replace(microsecond=0).isoformat()
    except (ValueError, TypeError):
        return datetime.now(UTC).replace(microsecond=0).isoformat()
