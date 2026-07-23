# Codex OTLP 集成完整执行方案（v3 — 审查修订版）

## 修订说明

v3 审查发现 1 个 P0 + 3 个 P1 问题，本版修订：
- **P0-1**：`error_signature` 缺 `signature_key` 导致整批回滚 → 修复为兼容结构
- **P1-1**：usage 双来源部分指标不一致翻倍 → 本期不接 `codex.sse_event`（推迟 G3）
- **P1-2**：步骤 0 用 `http.server` 无法查看请求体 → 改用临时诊断脚本
- **P1-3**：测试只验证 item 构造不验证入库 → 补充端到端测试

## 1. 背景与目标

### 1.1 问题

codex agent 的 LLM 调用 `duration_ms` 始终为 0，P50/P95/P99 显示 `—`。API 错误（429 限流等）当前完全不可见。

### 1.2 目标

| # | 目标 | 事件来源 | 解决的问题 |
|---|------|---------|-----------|
| G1 | LLM 调用 P50/P95/P99 有真实值 | `codex.api_request` | duration_ms=0 → 有精确值 |
| G2 | API 错误（429/500）可捕获 | `codex.api_error` | 当前完全不可见 |
| ~~G3~~ | ~~Token 消耗实时采集~~ | ~~`codex.sse_event`~~ | **推迟**：usage 双来源翻倍问题需先解决 |

### 1.3 范围

**本期做**：
- 接收 OTLP logs，处理 2 个事件：`codex.api_request`、`codex.api_error`
- 新增 `backend/app/otlp/` 模块（router + service）
- 4318 端口 OTLP HTTP 接收端点

**本期不做**：
- 不处理 `codex.sse_event`（P1-1：usage 双来源翻倍，需先在 usage/service.py 加 source_id 过滤）
- 不处理 `codex.tool_result`（避免与 sessions 日志的 tool_call 重复）
- 不处理 OTLP traces / metrics
- 不改动前端（已有 duration 显示逻辑）
- 不改动数据库 schema

### 1.4 明确限制

**OTel traceId 与 sessions turn_id 不关联**：
- OTLP logs 的事件用 OTel traceId
- sessions 日志的 task span 用 codex turn_id
- 任务列表/任务详情不显示 OTel 的 llm_call 明细（被 `having sum(case when span_type='task' ...)` 过滤）
- 后续需 OTLP traces 实现关联，不在本期范围

## 2. 技术调研结论

### 2.1 Codex OTel 配置

- codex CLI v0.130+ 内置 OTel（用户 0.144.1 支持）
- 配置：`~/.codex/config.toml` 的 `[otel]` 部分
- 三个独立 pipeline：logs / traces / metrics，各有 exporter
- endpoint 必须含完整路径（如 `http://localhost:4318/v1/logs`）
- `log_user_prompt` 默认 `false`（不导出 prompt 明文）

### 2.2 OTLP logs 事件清单

| 事件名 | 关键属性 | 本期是否处理 |
|--------|---------|------------|
| `codex.api_request` | `duration`, `status`, `success`, `model`, `attempt` | ✅ G1 |
| `codex.api_error` | `http.status`, `error.message` | ✅ G2 |
| `codex.sse_event` | `event.kind`, token counts（response.completed 时） | ❌ 推迟（P1-1 翻倍） |
| `codex.tool_result` | `tool.name`, `success`, `duration` | ❌ 避免与 sessions 重复 |
| `codex.user_prompt` | `prompt.length`（内容 redacted） | ❌ 价值低 |
| `codex.tool_decision` | `decision`, `source` | ❌ 价值低 |
| `codex.conversation_starts` | model, reasoning, sandbox 策略 | ❌ 价值低 |

### 2.3 需运行时验证的假设

| 假设 | 风险 | 验证方法 |
|------|------|---------|
| `duration` 单位是毫秒 | 否则数值错 6 个数量级 | 步骤 0 真实数据验证 |
| `eventName` 在 log record 顶层 | 否则需 fallback 到 attributes | 步骤 0 真实数据验证 |
| codex 用 JSON 编码 | 否则需 protobuf 支持 | 步骤 0 真实数据验证 |
| codex 用 gzip 压缩 | 如用需解压（已实现） | 步骤 0 真实数据验证 |
| `codex.sse_event` 的 token counts 字段名 | 字段名未确证 | 步骤 0 真实数据验证 |

## 3. 架构设计

### 3.1 整体架构

```
codex 运行
  ├── OTel logs 导出（实时） → localhost:4318/v1/logs → OTLP 接收端点
  │     ├── codex.api_request  → perf_signals (span_type='llm_call')
  │     └── codex.api_error    → observed_facts (fact_type='error') + error_signatures
  │
  └── sessions 日志（批量） → ~/.codex/sessions/ → collector_client
        └── task_complete    → perf_signals (span_type='task')
```

### 3.2 端口规划

| 端口 | 用途 |
|------|------|
| 8765 | 现有 dev_server（dashboard API） |
| 4318 | **新增** OTLP 接收端点 |
| 5173 | 现有前端 vite |

### 3.3 进程模型：同进程双 listener

4318 listener 在守护线程中运行，共享进程内 `write_lock`，直接调用 `ingest_telemetry`。

- 用**单线程 `HTTPServer`**（OTLP 请求本就被 write_lock 串行化，多线程无益）
- 避免跨进程 SQLite 写锁竞争

### 3.4 模块边界

新增 `backend/app/otlp/`：
- `router.py` — HTTP Handler 薄层（gzip 解压、Content-Type 校验、body 大小限制）
- `service.py` — OTLP logs → batch dict 翻译（3 个事件处理函数）

## 4. 详细设计

### 4.1 Codex 配置

`~/.codex/config.toml` 追加：

```toml
[otel]
environment = "dev"
log_user_prompt = false

[otel.exporter.otlp-http]
endpoint = "http://localhost:4318/v1/logs"
protocol = "json"
```

### 4.2 OTLP 接收端点

#### 4.2.1 `backend/app/otlp/router.py`

```python
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
            except OSError as exc:
                self._respond(400, {"error": "invalid_gzip"})
                return None
        content_type = self.headers.get("Content-Type", "").lower()
        if "protobuf" in content_type:
            self._respond(415, {"error": "unsupported_media_type",
                               "hint": "请配置 protocol = json"})
            return None
        return raw.decode("utf-8")

    def _read_body_discard(self) -> None:
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
```

#### 4.2.2 `backend/app/otlp/service.py`

```python
"""OTLP logs → agent-observer batch dict 翻译。"""
from __future__ import annotations

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

    处理 2 个事件（v3 审查修订：推迟 sse_event）：
    - codex.api_request → perf_signals (span_type='llm_call')
    - codex.api_error → observed_facts (fact_type='error')
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
        logger.warning("OTLP logs 收到 %d 条但全部跳过", skipped)

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
    """同时检查 eventName 和 attributes["event.name"]。"""
    event_name = log_record.get("eventName", "")
    if event_name:
        return event_name
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
    # sse_event 推迟到后续切片（P1-1：usage 双来源翻倍）
    return None


# ---------- 事件处理器 ----------

def _build_api_request_item(log_record: dict) -> dict | None:
    """codex.api_request → perf_signals (span_type='llm_call')。"""
    attrs = _flatten_attributes(log_record.get("attributes", []))
    duration = attrs.get("duration")
    if duration is None:
        return None

    trace_id = log_record.get("traceId", "")
    span_id = log_record.get("spanId", "")
    if not trace_id or not span_id:
        return None

    # TODO: 步骤 0 验证 duration 单位，当前假设毫秒
    duration_ms = int(round(float(duration)))
    success = attrs.get("success", True)
    model = attrs.get("model", "")
    status_code = attrs.get("status")
    attempt = attrs.get("attempt", 1)
    occurred_at = _nano_to_iso(log_record.get("timeUnixNano", "0"))

    perf_signal = {
        "trace_id": trace_id,
        "span_id": span_id,
        "span_type": "llm_call",
        "span_name": "codex.api_request",
        "duration_ms": duration_ms,
        "ttft_ms": 0,
        "tps": 0.0,
        "status": "ok" if success else "error",
        "error": "" if success else f"http_{status_code}",
        "model": model,
        "tool_name": "",
        "occurred_at": occurred_at,
    }

    return {
        "source_event_id": f"otel-{trace_id}-{span_id}",
        "fact_type": "perf",
        "category": "llm_call",
        "quality": "high",
        "severity": "low" if success else "medium",
        "summary": f"LLM API 调用 ({model}, {duration_ms}ms, attempt={attempt})",
        "occurred_at": occurred_at,
        "source_refs": {
            "conversation_ref": attrs.get("conversation.id", "") or attrs.get("conversation_id", ""),
            "session_ref": "",
        },
        "source_specific": {"source_template": "codex.otel.logs.v1"},
        "perf_signals": [perf_signal],
    }


def _build_api_error_item(log_record: dict) -> dict | None:
    """codex.api_error → observed_facts (fact_type='error')。

    P0-1 修复：error_signature 必须含 signature_key（ingest 强制下标取值）。
    error_signatures 表只有 signature_key/category/first_seen_at/last_seen_at/occurrences 列，
    http_status/error_message 放入 source_specific 而非 error_signature。
    """
    import hashlib

    attrs = _flatten_attributes(log_record.get("attributes", []))
    http_status = attrs.get("http.status") or attrs.get("http_status") or 0
    error_message = attrs.get("error.message") or attrs.get("error_message") or ""
    occurred_at = _nano_to_iso(log_record.get("timeUnixNano", "0"))

    trace_id = log_record.get("traceId", "")
    span_id = log_record.get("spanId", "")
    source_event_id = f"otel-err-{trace_id}-{span_id}" if trace_id and span_id else f"otel-err-{log_record.get('timeUnixNano', '')}"

    # P0-1: signature_key 是必需字段，ingest 用 error["signature_key"] 直接取值
    msg_hash = hashlib.sha256(error_message.encode("utf-8")).hexdigest()[:12] if error_message else "no_msg"
    signature_key = f"api_error:http_{http_status or 0}:{msg_hash}"

    return {
        "source_event_id": source_event_id,
        "fact_type": "error",
        "category": "api_error",
        "quality": "high",
        "severity": "high" if int(http_status) >= 500 else "medium",
        "summary": f"API 错误 HTTP {http_status}: {error_message[:200]}",
        "occurred_at": occurred_at,
        "source_refs": {
            "conversation_ref": attrs.get("conversation.id", "") or attrs.get("conversation_id", ""),
            "session_ref": "",
        },
        "source_specific": {
            "source_template": "codex.otel.logs.v1",
            "http_status": int(http_status) if http_status else None,
            "error_message": error_message[:500],
        },
        "error_signature": {
            "signature_key": signature_key,
            "category": "api_error",
        },
    }


# _build_sse_event_item 已移除（P1-1：usage 双来源翻倍，推迟到后续切片）


# ---------- 工具函数 ----------

def _flatten_attributes(attrs: list) -> dict:
    result = {}
    for attr in attrs:
        key = attr.get("key")
        if not key:
            continue
        value = attr.get("value", {})
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


def _nano_to_iso(nano_str: str) -> str:
    try:
        nano = int(nano_str)
        seconds = nano // 1_000_000_000
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=0).isoformat()
    except (ValueError, OSError):
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
```

### 4.3 dev_server.py 启动变更

```python
def _start_otlp_server(otlp_port: int) -> None:
    from http.server import HTTPServer
    from app.otlp.router import OtlpHandler
    try:
        otlp_server = HTTPServer(("127.0.0.1", otlp_port), OtlpHandler)
        logger.info("OTLP 接收端点: http://127.0.0.1:%d/v1/logs", otlp_port)
        otlp_server.serve_forever()
    except OSError as exc:
        if "address already in use" in str(exc).lower():
            logger.error("OTLP 端口 %d 已被占用", otlp_port)
        else:
            raise

# __main__ 中
otlp_port = int(os.environ.get("AGENT_OBSERVER_OTLP_PORT", "4318"))
otlp_thread = threading.Thread(target=_start_otlp_server, args=(otlp_port,), daemon=True)
otlp_thread.start()
```

## 5. 数据映射

### 5.1 两个事件的数据映射（v3 审查修订：移除 sse_event）

| 事件 | → observed_facts | → perf_signals / error_signatures |
|------|-----------------|----------------------------------|
| `codex.api_request` | fact_type=perf, category=llm_call | span_type=llm_call, duration_ms=精确值 |
| `codex.api_error` | fact_type=error, category=api_error | error_signatures (signature_key, category) |

### 5.2 去重策略

- collector_id=`otlp-receiver`, source_id=`codex-otel`（与 sessions 的 `codex-local` 区分）
- source_event_id 用 `otel-{traceId}-{spanId}`（每事件唯一）
- observed_facts unique index 防重复
- perf_signals upsert 语义

### 5.3 与 sessions 日志不重复

| span_type | OTLP logs 来源 | sessions 日志来源 | 重复？ |
|-----------|---------------|------------------|--------|
| llm_call | ✅ codex.api_request | ❌ sessions 不产生 llm_call | 不重复 |
| task | ❌ OTLP 不产生 task | ✅ task_complete | 不重复 |
| tool_call | ❌ 本期不处理 | ✅ function_call | 不重复 |
| usage | ❌ 本期不处理（推迟） | ✅ token_count | 不重复 |

**v3 审查修订**：本期不接 `codex.sse_event`，避免 usage 双来源翻倍。后续切片需先在 `usage/service.py` 加 source_id 过滤参数再接入。

## 6. 测试策略

### 6.1 后端测试

`backend/tests/test_otlp_service.py`（含端到端测试，P1-3 修复）：
1. test_process_otlp_logs_extracts_api_request
2. test_process_otlp_logs_extracts_api_error
3. test_process_otlp_logs_skips_unknown_event
4. test_process_otlp_logs_dedup
5. test_process_otlp_logs_empty
6. test_extract_event_name_from_eventName
7. test_extract_event_name_from_attributes
8. test_build_api_request_item_missing_duration
9. test_build_api_request_item_missing_trace_id
10. test_build_api_request_item_error_status
11. test_build_api_error_item_has_signature_key（P0-1 回归）
12. test_nano_to_iso
13. test_flatten_attributes

**端到端测试（P1-3 修复）**：
14. test_otlp_logs_end_to_end_api_request（OTLP JSON → process_otlp_logs → 断言 perf_signals 有行）
15. test_otlp_logs_end_to_end_api_error（OTLP JSON → process_otlp_logs → 断言 error_signatures 表有 signature_key）
16. test_otlp_logs_end_to_end_mixed_events（一个 OTLP 请求含 api_request + api_error → 断言两张表都有数据，无回滚）
17. test_otlp_logs_end_to_end_dedup（同一 OTLP JSON 重复发送 → 断言行数不翻倍）

`backend/tests/test_otlp_router.py`（HTTP 层）：
18. test_handle_logs_returns_200
19. test_handle_logs_returns_400_on_invalid_json
20. test_handle_logs_returns_413_on_oversized_body
21. test_handle_logs_returns_415_on_protobuf
22. test_handle_logs_decompresses_gzip
23. test_handle_traces_returns_200
24. test_handle_metrics_returns_200

### 6.2 Playwright 验证

1. 启动后端（含 4318）
2. 配置 codex OTel
3. 运行 codex 产生真实 OTLP 数据
4. 验证 LLM 调用 P50/P95/P99 有值
5. 验证失败时间线显示 API 错误（如有）

## 7. 实施步骤

### 步骤 0：验证真实 OTLP 数据（必须先做）

**P1-2 修复**：不用 `python -m http.server`（不打印请求体），改用临时诊断脚本 `backend/_tmp_otlp_probe.py`（约 30 行，诊断后删除）：

```python
"""临时 OTLP 探测脚本：打印收到的请求头和请求体。"""
import gzip, json
from http.server import HTTPServer, BaseHTTPRequestHandler

class ProbeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        encoding = self.headers.get("Content-Encoding", "")
        if "gzip" in encoding.lower():
            raw = gzip.decompress(raw)
        print(f"\n=== {self.path} ===")
        print(f"Content-Type: {self.headers.get('Content-Type')}")
        print(f"Content-Encoding: {encoding}")
        try:
            data = json.loads(raw)
            print(json.dumps(data, indent=2, ensure_ascii=False)[:5000])
        except Exception:
            print(f"RAW ({len(raw)} bytes): {raw[:500]}")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"success":{}}')
    def log_message(self, *args): pass

HTTPServer(("127.0.0.1", 4318), ProbeHandler).serve_forever()
```

验证步骤：
1. 启动 `python backend/_tmp_otlp_probe.py`
2. 配置 codex OTel 导出到 `http://localhost:4318/v1/logs`
3. 运行 `codex exec "echo hello"`
4. 检查脚本输出，确认：
   - codex 是否导出 logs
   - Content-Type / Content-Encoding
   - eventName 位置（顶层 vs attributes）
   - duration 字段值和单位（对比 codex 实际耗时判断毫秒/纳秒/秒）
5. 根据验证结果调整 service.py 代码
6. 验证完成后删除 `_tmp_otlp_probe.py`

### 步骤 1：创建 otlp 模块
### 步骤 2：修改 dev_server.py
### 步骤 3：写 pytest
### 步骤 4：配置 codex OTel
### 步骤 5：启动后端 + 运行 codex
### 步骤 6：Playwright 验证
### 步骤 7：对抗式审查

## 8. 已知限制与风险

### 8.1 需运行时验证

| 假设 | 风险 |
|------|------|
| duration 单位是毫秒 | 否则数值错 6 个数量级 |
| eventName 在顶层 | 否则需 fallback |
| codex 用 JSON 编码 | 否则需 protobuf 支持 |

### 8.2 架构限制

- OTel traceId 与 sessions turn_id 不关联
- 任务列表/详情不显示 OTel llm_call 明细
- 本期不接 sse_event（usage 翻倍问题需先在 usage/service.py 加 source_id 过滤）

### 8.3 运维风险

- 4318 handler 异常有 try/except 兜底
- request body 限制 10MB
- 单线程 HTTPServer 避免线程爆炸
- OTLP 导出失败不阻塞 codex（异步导出）

## 9. 文件变更清单

| 文件 | 操作 |
|------|------|
| `backend/app/otlp/__init__.py` | 新增 |
| `backend/app/otlp/router.py` | 新增 |
| `backend/app/otlp/service.py` | 新增 |
| `backend/app/dev_server.py` | 修改（加 4318 listener） |
| `backend/tests/test_otlp_service.py` | 新增 |
| `backend/tests/test_otlp_router.py` | 新增 |
| `~/.codex/config.toml` | 修改（加 [otel] 配置） |
