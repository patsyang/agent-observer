# Codex OTLP 集成设计方案（v2 — 审查修订版）

## 修订说明

本版本根据对抗式审查报告修订，解决 4 个 P0 问题和 8 个 P1 问题：
- **P0-1**：明确 OTel traceId 与 sessions turn_id 不关联的限制，降级目标
- **P0-2**：增加"先验证 duration 单位再实施"步骤
- **P0-3**：增加 gzip 解压和 Content-Type 校验
- **P0-4**：同时检查 `eventName` 和 `attributes["event.name"]`
- **P1-1**：删除死代码 `_extract_agent_type`
- **P1-2**：batch_id 加毫秒精度避免冲突
- **P1-3**：删除双重 commit
- **P1-4**：删除错误的 `analytics_enabled` 配置
- **P1-5**：改用单线程 HTTPServer（OTLP 本就被 write_lock 串行化）
- **P1-6**：增加 request body 大小限制
- **P1-7**：traceId/spanId 缺失时跳过而非 fallback
- **P1-8**：补充 HTTP 层测试

---

## 1. 背景与目标

### 1.1 问题

当前 codex agent 的 LLM 调用（`span_type='llm_call'`）的 `duration_ms` 始终为 0，导致性能观测页面 P50/P95/P99 显示 `—`。

根因：codex 的 sessions 日志文件（`~/.codex/sessions/*.jsonl`）中的 `task_complete` 事件只记录 turn 级总耗时（含 LLM 调用 + 工具调用 + 用户等待），不记录每次 LLM API 调用的单独耗时。

### 1.2 目标（审查修订后）

**核心目标（能达成）**：
- ✅ 性能观测页面的 LLM 调用卡片 P50/P95/P99 显示真实 duration 值
- ✅ `get_perf_summary` 的 `llm_call_count` 增加（OTel 提供每次 LLM 调用）
- ✅ `latency.llm_call.duration_*` 百分位有真实数据

**明确不在本期目标内（P0-1 限制）**：
- ❌ 任务列表的"调用数"不会因 OTel 数据增加（OTel traceId 与 sessions turn_id 不同，OTel llm_call 被 `having sum(case when span_type='task' ...)` 过滤）
- ❌ 任务详情抽屉不显示 OTel 的 llm_call 明细（trace_id 不关联）
- 后续可通过 OTLP traces 的 span parent 关联实现，但不在本期范围

### 1.3 范围

- **本期**：接收 OTLP logs（`codex.api_request` 事件），提取单次 LLM 调用 duration
- **后续**（不在本期范围）：OTLP traces（span 层级关联）、OTLP metrics（聚合统计）

### 1.4 非目标

- 不改动前端（已有 duration 显示逻辑）
- 不改动数据库 schema（perf_signals 已有 duration_ms 字段）
- 不替换现有 sessions 日志采集（OTel 是补充数据源）
- 不处理 OTLP metrics 直方图
- 不处理 OTLP traces

## 2. 技术调研结论

### 2.1 Codex OTel 配置

- codex CLI v0.130+ 内置 OTel 支持（用户当前 0.144.1，支持）
- 配置位置：`~/.codex/config.toml`（用户级，项目级会被忽略）
- 三个独立 pipeline：logs / traces / metrics，各有独立 exporter
- `metrics_exporter` 默认是 `statsig`（OpenAI 内部），需显式覆盖为 `otlp-http`（本期不配 metrics）
- endpoint 必须含完整路径（如 `http://localhost:4318/v1/logs`），codex 不自动追加
- `log_user_prompt` 默认 `false`（不导出 prompt 明文）

**审查修正（P1-4）**：删除了原方案中错误的 `analytics_enabled = true` 配置。该配置键不存在于官方文档，analytics 控制的是"匿名使用数据回传 OpenAI"，与 OTel logs 导出无关。OTel logs 导出只受 `[otel] exporter` 控制。

### 2.2 OTLP HTTP 协议

- 标准端口：4318（HTTP）/ 4317（gRPC）
- 端点：`/v1/traces`、`/v1/metrics`、`/v1/logs`
- 支持 JSON 编码（`protocol = "json"`），无需 protobuf 依赖
- 支持 gzip 压缩（`Content-Encoding: gzip`）
- Content-Type: `application/json`（JSON）或 `application/x-protobuf`（protobuf）
- 成功响应：HTTP 200

### 2.3 Codex OTel 数据清单

**Logs（结构化事件）**：
| 事件名 | 关键属性 | 用途 |
|--------|---------|------|
| `codex.api_request` | `duration`, `status`, `success`, `model`, `attempt` | **本期目标：LLM 调用 duration** |

**注意（P0-4 修正）**：事件名可能出现在 `log_record.eventName` 或 `log_record.attributes` 中的 `event.name` 键，需同时检查。

### 2.4 数据获取策略

**首选：OTLP logs 的 `codex.api_request` 事件**
- OpenAI 官方文档明确列出 `codex.api_request` log event 包含 `duration` 字段
- 每次 LLM API 调用一个 log event（推断，需运行时验证）

---

## 3. 架构设计

### 3.1 整体架构

```
codex 运行
  ├── OTel 导出（实时） → localhost:4318/v1/logs → OTLP 接收端点
  │     └── 解析 codex.api_request → batch dict → ingest_telemetry
  │                                                  ↓
  │                                          perf_signals (span_type='llm_call')
  │                                          trace_id = OTel traceId（与 task 不关联）
  │
  └── sessions 日志（批量） → ~/.codex/sessions/ → collector_client
        └── 解析 task_complete → batch dict → ingest_telemetry
                                                     ↓
                                             perf_signals (span_type='task')
                                             trace_id = codex turn_id
```

**审查确认（P0-1）**：OTel traceId 与 sessions turn_id 是两个不同的 ID 系统，无法关联。OTel 的 llm_call span 在 `get_perf_summary` 的 `latency.llm_call` 统计中有效（按 span_type 过滤），但在 `get_perf_tasks` 中被过滤（按 trace_id 分组 + having task span）。

### 3.2 端口规划

| 端口 | 用途 | 监听地址 |
|------|------|---------|
| 8765 | 现有 dev_server（dashboard API + telemetry ingest） | 127.0.0.1 |
| 4318 | **新增** OTLP 接收端点 | 127.0.0.1 |
| 5173 | 现有前端 vite dev server | 127.0.0.1 |

### 3.3 进程模型：方案 C（同进程双 listener，审查确认）

在 `dev_server.py` 的 `__main__` 中，主线程启动 8765 server，额外起一个守护线程启动 4318 server。

**审查修正（P1-5）**：4318 listener 改用**单线程 `HTTPServer`**（不是 `ThreadingHTTPServer`）。理由：
1. OTLP 请求本就被 `write_lock` 串行化，多线程无益
2. 单线程避免线程爆炸风险
3. OTLP 请求频率低（codex 每次 LLM 调用一个 log event，批量异步导出）

**风险（P2-5 确认）**：4318 handler 的未捕获异常理论上可能影响进程稳定性，但有 try/except 兜底。

### 3.4 模块边界

新增 `backend/app/otlp/` 模块：
- `__init__.py`
- `router.py` — HTTP Handler 薄层（解析 OTLP JSON body，调用 service）
- `service.py` — OTLP logs → batch dict 翻译（业务逻辑）

---

## 4. 详细设计

### 4.1 Codex 配置变更

在 `~/.codex/config.toml` 末尾追加：

```toml
# OpenTelemetry logs 导出配置（agent-observer 接收）
[otel]
environment = "dev"
log_user_prompt = false

# Logs 导出器：codex.api_request 等事件
[otel.exporter.otlp-http]
endpoint = "http://localhost:4318/v1/logs"
protocol = "json"
```

**注意**：
- 只配置 logs exporter（不配 traces/metrics，减少噪音）
- `protocol = "json"` 是必须的（handler 只支持 JSON，不支持 protobuf）
- `log_user_prompt = false` 保护隐私

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

_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB 上限（P1-6）


class OtlpHandler(BaseHTTPRequestHandler):
    """OTLP HTTP 协议处理器。"""

    def do_POST(self) -> None:
        if self.path == "/v1/logs":
            self._handle_logs()
        elif self.path == "/v1/traces":
            # 本期不处理 traces，返回 200 避免客户端重试
            self._read_body_discard()
            self._respond(200, {"success": {}})
        elif self.path == "/v1/metrics":
            self._read_body_discard()
            self._respond(200, {"success": {}})
        else:
            self._respond(404, {"error": "not_found"})

    def _handle_logs(self) -> None:
        try:
            body = self._read_body()  # P0-3: 处理 gzip + Content-Type 校验
            if body is None:
                return  # _read_body 已响应错误
            data = json.loads(body) if body else {}
            with write_lock() as conn:
                result = process_otlp_logs(conn, data)
                # P1-3: 不显式 commit，ingest_telemetry 内部已 commit
            self._respond(200, {"success": {}, **result})
        except json.JSONDecodeError as exc:
            logger.warning("OTLP logs JSON 解析失败: %s", exc)
            self._respond(400, {"error": "invalid_json"})
        except Exception as exc:
            logger.exception("OTLP logs 处理失败")
            self._respond(500, {"error": str(exc)})

    def _read_body(self) -> str | None:
        """读取请求体，处理 gzip 解压和大小限制。"""
        length = int(self.headers.get("Content-Length", 0))
        if length > _MAX_BODY_SIZE:  # P1-6
            self._respond(413, {"error": "body_too_large"})
            return None
        if length == 0:
            return ""
        raw = self.rfile.read(length)
        # P0-3: 检查 Content-Encoding
        encoding = self.headers.get("Content-Encoding", "").lower()
        if "gzip" in encoding:
            try:
                raw = gzip.decompress(raw)
            except OSError as exc:
                logger.warning("OTLP gzip 解压失败: %s", exc)
                self._respond(400, {"error": "invalid_gzip"})
                return None
        # P0-3: 检查 Content-Type
        content_type = self.headers.get("Content-Type", "").lower()
        if "protobuf" in content_type:
            logger.warning("OTLP 收到 protobuf 编码，仅支持 JSON")
            self._respond(415, {"error": "unsupported_media_type", "hint": "请配置 protocol = json"})
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
        # P2-1: 用 info 级别记录 OTLP 请求
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

# 合成 collector/source 元数据
_OTLP_COLLECTOR_ID = "otlp-receiver"
_OTLP_SOURCE_ID = "codex-otel"
_OTLP_AGENT_TYPE = "codex"
_OTLP_SOURCE_KIND = "codex_otel"
_OTLP_AGENT_VERSION = "codex-otel-0.1"


def process_otlp_logs(conn, data: dict) -> dict:
    """处理 OTLP logs，提取 codex.api_request 事件写入 perf_signals。

    Args:
        conn: SQLite 连接（调用方负责 write_lock）
        data: OTLP logs JSON 请求体

    Returns:
        {"accepted": int, "duplicates": int, "skipped": int}
    """
    items = []
    skipped = 0

    for resource_logs in data.get("resourceLogs", []):
        for scope_logs in resource_logs.get("scopeLogs", []):
            for log_record in scope_logs.get("logRecords", []):
                # P0-4: 同时检查 eventName 和 attributes["event.name"]
                event_name = _extract_event_name(log_record)
                if event_name == "codex.api_request":
                    item = _build_api_request_item(log_record)
                    if item:
                        items.append(item)
                    else:
                        skipped += 1
                else:
                    skipped += 1

    # P0-4: 收到数据但全部 skip 时记录 warning
    if not items and skipped > 0:
        logger.warning("OTLP logs 收到 %d 条记录但全部跳过（无 codex.api_request 事件）", skipped)

    if not items:
        return {"accepted": 0, "duplicates": 0, "skipped": skipped}

    batch = _wrap_batch(items)
    result = ingest_telemetry(conn, batch)
    accepted = result.get("accepted", 0)
    if accepted > 0:
        logger.info("OTLP logs 入库: accepted=%d, duplicates=%d, skipped=%d",
                    accepted, result.get("duplicates", 0), skipped)
    return {
        "accepted": accepted,
        "duplicates": result.get("duplicates", 0),
        "skipped": skipped,
    }


def _extract_event_name(log_record: dict) -> str:
    """P0-4: 同时检查 eventName 和 attributes["event.name"]。"""
    # OTel Logs Data Model 1.1+ 用顶层 eventName
    event_name = log_record.get("eventName", "")
    if event_name:
        return event_name
    # 旧版 SDK 用 attributes["event.name"]
    for attr in log_record.get("attributes", []):
        if attr.get("key") == "event.name":
            value = attr.get("value", {})
            return value.get("stringValue", "")
    return ""


def _build_api_request_item(log_record: dict) -> dict | None:
    """将 codex.api_request log event 转换为 agent-observer item。"""
    attrs = _flatten_attributes(log_record.get("attributes", []))

    duration = attrs.get("duration")
    if duration is None:
        logger.debug("codex.api_request 缺少 duration 字段，跳过")
        return None

    # P0-2: duration 单位需运行时验证，当前假设毫秒
    # TODO: 首次运行时用真实数据验证单位，如果不是毫秒需调整
    duration_ms = int(round(float(duration)))

    trace_id = log_record.get("traceId", "")
    span_id = log_record.get("spanId", "")

    # P1-7: traceId/spanId 缺失时跳过（无法可靠去重）
    if not trace_id or not span_id:
        logger.debug("codex.api_request 缺少 traceId/spanId，跳过")
        return None

    success = attrs.get("success", True)
    model = attrs.get("model", "")
    status_code = attrs.get("status")

    # 构造 source_event_id（用于去重）
    source_event_id = f"otel-{trace_id}-{span_id}"

    # 构造 occurred_at（纳秒 → ISO）
    occurred_at = _nano_to_iso(log_record.get("timeUnixNano", "0"))

    # 构造 perf_signal
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

    # P2-4: 同时检查 conversation.id 和 conversation_id
    conversation_ref = attrs.get("conversation.id", "") or attrs.get("conversation_id", "")

    return {
        "source_event_id": source_event_id,
        "fact_type": "perf",
        "category": "llm_call",
        "quality": "high",
        "severity": "low" if success else "medium",
        "summary": f"LLM API 调用 ({model}, {duration_ms}ms)",
        "occurred_at": occurred_at,
        "source_refs": {
            "conversation_ref": conversation_ref,
            "session_ref": "",
        },
        "source_specific": {
            "source_template": "codex.otel.logs.v1",
        },
        "perf_signals": [perf_signal],
    }


def _flatten_attributes(attrs: list) -> dict:
    """将 OTLP attributes 数组扁平化为 dict。"""
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
    """Unix 纳秒时间戳 → ISO 8601 字符串。"""
    try:
        nano = int(nano_str)
        # 用整除避免浮点精度问题（P0-2 审查建议）
        seconds = nano // 1_000_000_000
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=0).isoformat()
    except (ValueError, OSError):
        return datetime.now(UTC).replace(microsecond=0).isoformat()


def _wrap_batch(items: list[dict]) -> dict:
    """包装为 agent-observer batch dict。"""
    # P1-2: batch_id 加毫秒精度避免同秒冲突
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
    """启动 OTLP HTTP 接收端点（4318）。

    P1-5: 用单线程 HTTPServer（OTLP 请求本就被 write_lock 串行化）。
    """
    from http.server import HTTPServer  # 单线程，不是 ThreadingHTTPServer
    from app.otlp.router import OtlpHandler

    try:
        otlp_server = HTTPServer(("127.0.0.1", otlp_port), OtlpHandler)
        logger.info("OTLP 接收端点: http://127.0.0.1:%d/v1/logs", otlp_port)
        otlp_server.serve_forever()
    except OSError as exc:
        if "address already in use" in str(exc).lower():
            logger.error("OTLP 端口 %d 已被占用，OTLP 接收端点未启动", otlp_port)
        else:
            raise


# 在 __main__ 块中（8765 server 启动前）
otlp_port = int(os.environ.get("AGENT_OBSERVER_OTLP_PORT", "4318"))
otlp_thread = threading.Thread(target=_start_otlp_server, args=(otlp_port,), daemon=True)
otlp_thread.start()
```

### 4.4 数据映射

#### 4.4.1 OTLP log event → perf_signals 字段映射

| perf_signals 字段 | OTLP 来源 | 说明 |
|-------------------|----------|------|
| `signal_id` | `perf-{fact_id}-{span_id}` | 由 ingest_telemetry 自动生成 |
| `fact_id` | 由 ingest_telemetry 从 source_event_id 派生 | |
| `trace_id` | log record 的 `traceId` | OTel traceId（与 task turn_id **不关联**） |
| `span_id` | log record 的 `spanId` | OTel spanId |
| `span_type` | 硬编码 `"llm_call"` | |
| `span_name` | 硬编码 `"codex.api_request"` | |
| `duration_ms` | attributes 的 `duration` | **核心字段**（单位待验证） |
| `ttft_ms` | `0` | logs 不含 TTFT |
| `tps` | `0.0` | logs 不含 TPS |
| `status` | `ok` if `success=true` else `error` | |
| `error` | `""` or `http_{status}` | |
| `model` | attributes 的 `model` | |
| `agent_type` | `"codex"`（batch 层硬编码） | |
| `occurred_at` | `timeUnixNano` → ISO | |

#### 4.4.2 去重策略

- **source_event_id** = `otel-{traceId}-{spanId}`：每次 LLM 调用唯一
- **collector_id** = `otlp-receiver`：与 collector_client 区分
- **source_id** = `codex-otel`：与 sessions 日志的 `codex-local` 区分
- **observed_facts 去重**：unique index on `(collector_id, source_id, source_event_id)`
- **perf_signals 去重**：`signal_id = perf-{fact_id}-{span_id}`，upsert 语义

### 4.5 与现有采集器协同

#### 4.5.1 数据来源分工

| 数据维度 | OTel logs（新） | sessions 日志（现有） |
|---------|----------------|---------------------|
| LLM 调用 duration | ✅ 精确（每次调用） | ❌ 只有 turn 总耗时 |
| TTFT | ❌ logs 不含 | ✅ task_complete.time_to_first_token_ms |
| Turn 级数据 | ❌ | ✅ task_complete |

#### 4.5.2 trace_id 不关联的影响（P0-1 确认）

| 统计项 | 是否受 OTel 数据影响 | 原因 |
|--------|---------------------|------|
| `latency.llm_call.duration_*` | ✅ 有真实值 | 按 `span_type='llm_call'` 过滤，不依赖 trace_id |
| `latency.llm_call.duration_sample_count` | ✅ 增加 | 同上 |
| `totals.llm_call_count` | ✅ 增加 | 按 `span_type='llm_call'` 计数 |
| `totals.task_count` | ❌ 不变 | 按 `span_type='task'` 的 distinct trace_id 计数 |
| 任务列表的 `call_count` | ❌ 不变 | `get_perf_tasks` 按 trace_id 分组 + having task span，OTel trace_id 无 task span 被过滤 |
| 任务详情的 spans 列表 | ❌ 不显示 OTel | `get_perf_task_detail` 按 task 的 trace_id 查询 |

#### 4.5.3 不会重复

- OTel `codex.api_request` → `span_type='llm_call'`（LLM 调用级，trace_id = OTel traceId）
- sessions `task_complete` → `span_type='task'`（turn 级，trace_id = codex turn_id）
- 两者粒度不同，span_type 不同，trace_id 不同，不会产生重复 perf_signals

---

## 5. 实施步骤（审查修订）

### 步骤 0（P0-2/P0-3/P0-4 验证）：先用真实数据确认假设

**在写任何代码前**，必须先验证以下假设：
1. codex 0.144.1 是否真的导出 OTLP logs
2. `codex.api_request` log event 的 JSON 结构（`eventName` vs `attributes["event.name"]`）
3. `duration` 字段的单位（毫秒？纳秒？秒？）
4. codex 是否用 gzip 压缩
5. Content-Type 是 `application/json` 还是其他

**验证方法**：
1. 启动一个临时 HTTP 监听端点（如 `python -m http.server 4318`）接收 OTLP 数据
2. 配置 codex OTel 导出到该端点
3. 运行 `codex exec "echo hello"`
4. 检查接收到的请求体，确认上述 5 个假设

### 步骤 1：创建 `backend/app/otlp/` 模块

根据步骤 0 的验证结果调整代码（特别是 duration 单位和 eventName 位置）。

### 步骤 2：修改 `dev_server.py`

### 步骤 3：写 pytest

### 步骤 4：配置 codex OTel

### 步骤 5：启动后端 + 运行 codex 产生真实 OTel 数据

### 步骤 6：Playwright 验证

### 步骤 7：对抗式审查

---

## 6. 测试策略

### 6.1 后端测试（pytest）

新增 `backend/tests/test_otlp_service.py`：

1. **`test_process_otlp_logs_extracts_api_request`**：给定含 `codex.api_request` 的 OTLP JSON，验证 perf_signals 正确写入
2. **`test_process_otlp_logs_skips_non_api_request`**：非 `codex.api_request` 事件被跳过
3. **`test_process_otlp_logs_dedup`**：同一 OTLP JSON 重复发送，不产生重复行
4. **`test_process_otlp_logs_empty`**：空请求体不报错
5. **`test_nano_to_iso`**：纳秒时间戳正确转 ISO
6. **`test_flatten_attributes`**：OTLP attributes 数组正确扁平化
7. **`test_build_api_request_item_missing_duration`**：缺 duration 字段时返回 None
8. **`test_build_api_request_item_error_status`**：success=false 时 status="error"
9. **`test_extract_event_name_from_eventName`**：从顶层 `eventName` 提取事件名（P0-4）
10. **`test_extract_event_name_from_attributes`**：从 `attributes["event.name"]` 提取事件名（P0-4）
11. **`test_build_api_request_item_missing_trace_id`**：缺 traceId/spanId 时返回 None（P1-7）

新增 `backend/tests/test_otlp_router.py`（P1-8 补充 HTTP 层测试）：

12. **`test_handle_logs_returns_200_on_success`**：正常请求返回 200
13. **`test_handle_logs_returns_400_on_invalid_json`**：非 JSON body 返回 400
14. **`test_handle_logs_returns_413_on_oversized_body`**：超过 10MB 返回 413（P1-6）
15. **`test_handle_logs_returns_415_on_protobuf`**：protobuf Content-Type 返回 415（P0-3）
16. **`test_handle_logs_decompresses_gzip`**：gzip 压缩 body 正确解压（P0-3）
17. **`test_handle_traces_returns_200`**：/v1/traces 返回 200 避免重试
18. **`test_handle_metrics_returns_200`**：/v1/metrics 返回 200 避免重试

### 6.2 前端测试

不需要改动。

### 6.3 Playwright 验证

1. 启动后端（含 OTLP 接收端点 4318）
2. 配置 codex OTel 导出
3. 运行 codex 产生 OTel 数据
4. 验证性能观测页面 LLM 调用 P50/P95/P99 有真实值

---

## 7. 已知限制与风险

### 7.1 需运行时验证的假设（P0-2/P0-3/P0-4）

| 假设 | 风险 | 验证方法 |
|------|------|---------|
| `duration` 单位是毫秒 | 如果不是，P50/P95/P99 数值错 6 个数量级 | 步骤 0 用真实数据验证 |
| `eventName` 在 log record 顶层 | 如果在 attributes 中，需 fallback 逻辑 | 步骤 0 用真实数据验证 |
| codex 用 JSON 编码 | 如果用 protobuf，handler 返回 415 | 步骤 0 用真实数据验证 |
| codex 不用 gzip | 如果用 gzip，需解压（已实现） | 步骤 0 用真实数据验证 |

### 7.2 架构限制（P0-1）

- OTel traceId 与 sessions turn_id 不关联
- 任务列表/任务详情不显示 OTel 的 llm_call 明细
- 后续需 OTLP traces 实现关联

### 7.3 运维风险（P1-5/P1-6/P2-6）

- 4318 handler 异常有 try/except 兜底，不影响 8765 server
- request body 限制 10MB
- 单线程 HTTPServer 避免线程爆炸
- OTLP 导出失败不阻塞 codex 运行（异步导出），codex 会在后台重试

---

## 8. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/otlp/__init__.py` | 新增 | 模块初始化 |
| `backend/app/otlp/router.py` | 新增 | OTLP HTTP Handler（gzip/Content-Type 校验） |
| `backend/app/otlp/service.py` | 新增 | OTLP logs → batch dict 翻译 |
| `backend/app/dev_server.py` | 修改 | 新增 4318 listener 启动（单线程） |
| `backend/tests/test_otlp_service.py` | 新增 | service 层 pytest |
| `backend/tests/test_otlp_router.py` | 新增 | HTTP 层 pytest |
| `~/.codex/config.toml` | 修改 | 新增 [otel] logs 导出配置 |
