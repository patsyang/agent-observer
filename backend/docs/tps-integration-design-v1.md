# TPS 计算集成方案（v2 — 审查修订版）

## 修订说明

v1 审查发现 0 个 P0 + 3 个 P1，本版修订：
- **P1-1**：同批 OTLP logs 中 sse_event 与 api_request 处理顺序导致漏匹配 → 改为两阶段处理（先 ingest api_request，再处理 sse_event）
- **P1-2**：SQL 缺时间窗口下界 → 加 `occurred_at >= ? - 10min` 下界
- **P1-3**：UPDATE 的 commit 依赖 write_lock 隐性行为 → process_otlp_logs 末尾显式 commit
- **P2-1**：TPS 异常大值无上限校验 → 加 TPS > 1000 时置 0 并 warning
- **P2-3**：测试遗漏场景 → 补充 5 个测试用例

## 1. 背景与目标

### 1.1 问题

性能观测页面 codex LLM 调用的 TPS 均值/峰值显示 `—`。根因：所有数据源的 `tps` 字段恒为 0.0，没有任何样本同时携带「output token 数」和「generation duration」。

### 1.2 数据源现状

| 数据源 | token 数 | generation duration | 当前 tps |
|--------|---------|-------------------|---------|
| sessions 日志 task_complete | ❌ 无 | ❌ 只有 turn 总耗时（含工具调用） | 0.0 |
| sessions 日志 token_count | ✅ 有 output_tokens | ❌ 无 duration | 不写 perf_signal |
| OTLP api_request（已接） | ❌ 无 | ✅ 有 duration_ms（HTTP 请求总耗时） | 0.0 |
| OTLP sse_event（未接） | ✅ 有 output_token_count（response.completed 时） | ❌ 无 duration | — |

### 1.3 目标

| # | 目标 | 实现方式 |
|---|------|---------|
| G1 | TPS 均值/峰值有真实值 | sse_event 的 output_token_count + api_request 的 duration_ms |
| G2 | usage 不翻倍 | sse_event 不写 usage_signal，只用于 TPS 计算 |

### 1.4 范围

**本期做**：
- 接收 OTLP `codex.sse_event`（仅 `event.kind=response.completed`）
- 提取 `output_token_count`
- 用 `conversation.id` + 时间窗口关联最近的 api_request perf_signal
- UPDATE perf_signal.tps

**本期不做**：
- 不写 usage_signal（防翻倍）
- 不接 sse_event 的其他 event.kind（如 response.output_text.delta）
- 不改动前端（已有 tps 显示逻辑）
- 不改动数据库 schema

### 1.5 已知限制

- **TPS 偏低**：api_request 的 duration_ms 含网络/排队，不是纯 generation 时间。TPS = output_token_count / (http_duration_ms / 1000) 会比真实 generation TPS 低。
- **sse_event 先于 api_request 到达时丢失**：罕见场景，sse_event response.completed 理论上在 api_request 完成后才发出。
- **同一 conversation 并发 api_request**：如果 codex 在同一 conversation 并发发起多个 api_request（如多轮重试），关联可能匹配到错误的 perf_signal。

## 2. 技术调研结论

### 2.1 sse_event 数据结构（基于文档，需步骤 0 验证）

来源：last9.io 文档 + codex GitHub config.md + CSDN 实践博客

```
event.name = codex.sse_event
event.kind = response.completed  (仅此 kind 携带 token counts)
attributes:
  - input_token_count (intValue, responses only)
  - output_token_count (intValue, responses only)
  - cached_token_count (intValue, optional, responses only)
  - reasoning_token_count (intValue, optional, responses only)
  - conversation.id (stringValue)
  - event.timestamp (stringValue, ISO 格式)
  - event.kind (stringValue, 如 "response.completed")
```

注意：`codex.sse_event.duration_ms` 是 OTel metric histogram，不是 log event 的属性。sse_event log event 本身不携带 duration。

### 2.2 usage 翻倍机制

sessions 日志的 `token_count` 事件和 OTLP `sse_event` 都携带 token counts：
- token_count → fact（source_event_id 基于 turn_id）→ usage_signal
- sse_event → 如果也写 usage_signal → 同一 turn 的 token 数据被记录两次

ingest 的 duplicate 分支基于 `source_event_id` 去重，两个来源的 source_event_id 不同，不会互相去重。

**防翻倍方案**：sse_event 不写 usage_signal，只提取 output_token_count 用于 TPS 计算。

### 2.3 关联方式

sse_event response.completed 和 api_request 共享 `conversation.id`：
- api_request 先发出（HTTP 请求开始）
- sse_event response.completed 后发出（响应完成）
- 用 `conversation.id` + `sse_event.timestamp >= api_request.occurred_at` + 时间窗口（< 10 分钟）关联

## 3. 架构设计

### 3.1 处理流程

```
codex 运行
  ├── OTLP api_request → perf_signals (span_type='llm_call', tps=0.0)  [已实现]
  │
  └── OTLP sse_event (response.completed)
        ├── 提取 output_token_count + conversation.id + event.timestamp
        ├── 查询 perf_signals: 同一 conversation.id 的最近 llm_call span
        │   WHERE conversation_ref = ? AND span_type = 'llm_call'
        │     AND occurred_at <= ?  ORDER BY occurred_at DESC LIMIT 1
        ├── 计算 tps = output_token_count / (duration_ms / 1000)
        └── UPDATE perf_signals SET tps = ? WHERE signal_id = ?
```

### 3.2 模块边界

修改 `backend/app/otlp/service.py`：
- 新增 `_build_sse_event_handler(conn, log_record)` 函数
- 在 `process_otlp_logs` 中，对 sse_event 做特殊处理（不走 ingest_telemetry）
- 直接查询和更新 perf_signals 表

### 3.3 不走 ingest_telemetry 的原因

1. sse_event 不是新 fact，是已有 api_request perf_signal 的补充更新
2. 避免写 usage_signal 导致翻倍
3. 直接 UPDATE 更简单高效

## 4. 详细设计

### 4.1 service.py 修改

#### 4.1.1 新增 sse_event 处理函数

```python
_TPS_MAX_REASONABLE = 1000.0  # GPT-4o 峰值约 100 tps，1000 是保守上限（P2-1）


def _handle_sse_event(conn, log_record: dict) -> dict:
    """处理 codex.sse_event (response.completed)，更新最近 api_request 的 tps。

    不写新的 fact/usage_signal，只 UPDATE 已有 perf_signal.tps。
    """
    attrs = _flatten_attributes(log_record.get("attributes", []))
    event_kind = attrs.get("event.kind", "")

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
    # P1-2: 加 occurred_at >= ? 下界与 2.3 节设计对齐
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
```

#### 4.1.2 修改 process_otlp_logs

```python
def process_otlp_logs(conn, data: dict) -> dict:
    # P1-1: 两阶段处理。第一遍收集 items + sse_events，第二遍先 ingest 再处理 sse_event
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

    # 第二阶段 2：api_request 入库后，再处理 sse_event 做 SELECT + UPDATE
    tps_updated = 0
    for sse_record in sse_events:
        result = _handle_sse_event(conn, sse_record)
        tps_updated += result["tps_updated"]
        skipped += result["skipped"]

    # P1-3: 显式 commit，消除对 write_lock 隐性行为的依赖
    if tps_updated > 0:
        conn.commit()

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "skipped": skipped,
        "tps_updated": tps_updated,
    }
```

#### 4.1.3 新增工具函数

```python
def _safe_int(value) -> int:
    try:
        return int(value)
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
```

### 4.2 测试设计

1. `test_handle_sse_event_updates_tps` — 正常更新
2. `test_handle_sse_event_skips_non_completed` — 跳过非 response.completed
3. `test_handle_sse_event_skips_zero_tokens` — 跳过 output_token_count=0
4. `test_handle_sse_event_no_matching_perf_signal` — 未找到 api_request
5. `test_handle_sse_event_zero_duration_skipped` — duration_ms=0 不更新
6. `test_handle_sse_event_time_window_expired` — api_request 超过 10 分钟窗口不匹配（P1-2）
7. `test_handle_sse_event_tps_too_large_skipped` — TPS > 1000 置 0 不更新（P2-1）
8. `test_process_otlp_logs_sse_event_does_not_create_usage` — 不写 usage_signal（防翻倍）
9. `test_process_otlp_logs_mixed_api_request_and_sse` — 端到端：同批 logs 中 api_request 先入库，sse_event 更新 tps（P1-1 两阶段）
10. `test_process_otlp_logs_sse_before_api_request` — sse_event 先于 api_request 到达，不报错不更新
11. `test_process_otlp_logs_multi_turn_association` — 多轮对话关联：第 N 轮 sse_event 匹配第 N 轮 api_request
12. `test_process_otlp_logs_sse_event_commit_persisted` — 只有 sse_event 时 UPDATE 被持久化（P1-3 显式 commit）

### 4.3 步骤 0：验证 sse_event 真实数据

用临时探测脚本验证：
- sse_event 的 event.kind 值（确认 "response.completed"）
- token 字段名（确认 output_token_count，intValue 类型）
- sse_event 是否在 api_request 之后到达
- 同一 conversation 的 sse_event 和 api_request 时间差

## 5. 执行步骤

1. 步骤 0：验证 sse_event 真实数据（探测脚本 + codex 运行）
2. 步骤 1：修改 service.py（新增 _handle_sse_event + 修改 process_otlp_logs）
3. 步骤 2：写 pytest（7 个测试）
4. 步骤 3：启动后端 + codex 运行产生真实数据
5. 步骤 4：验证 perf_signal.tps 有值（SQL 查询）
6. 步骤 5：构建 perf rollups
7. 步骤 6：Playwright 验证 TPS 均值/峰值有值
8. 步骤 7：对抗式审查实现
9. 步骤 8：关闭服务 + 清理临时文件

## 6. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| sse_event 字段名与文档不符 | 中 | TPS 无法计算 | 步骤 0 验证真实数据 |
| sse_event 先于 api_request 到达 | 低 | TPS 丢失 | 可接受，罕见场景 |
| 同 conversation 并发 api_request | 低 | 关联到错误 span | 用最近时间窗口降低风险 |
| duration_ms 含网络开销导致 TPS 偏低 | 高 | TPS 值偏低但可用 | 已知限制，文档说明 |
| perf_signal 未找到（api_request 未入库） | 中 | TPS 不更新 | 可接受，sessions 日志兜底 |
