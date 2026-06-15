# Agent Observer 0.1 MVP 设计

## 版本定位

0.1 是 Agent Observer 的最小可用版本，目标是验证一条完整链路：

```text
Windows 用户下载客户端
  -> 解压运行 Go CLI exe
  -> 自动检测本机 Codex 环境
  -> 本地脱敏和断点续采
  -> 上报结构化 telemetry
  -> 服务端 SQLite 入库和聚合
  -> Dashboard 展示可读用户、账号、项目、错误和消息
```

0.1 只支持 Codex 本机环境，只支持 Windows x64 客户端，只提供 P0/P1 运行方式。

## 0.1 范围

### 必须交付

| 范围 | 内容 |
| --- | --- |
| 客户端 | Go 编译的 `agent-observer.exe`，Windows x64，zip 解压运行。 |
| 运行模式 | P0 `run-once` 一次性采集；P1 `start` 前台常驻采集。 |
| Codex 检测 | 自动检测 `.codex`、SQLite、sessions、history、logs、auth、installation id。 |
| 本地状态 | 使用 `%LOCALAPPDATA%\AgentObserver\agent-observer-state.sqlite` 保存配置、游标、outbox、诊断任务。 |
| 上报 | 只上报脱敏 telemetry、聚合指标、诊断结构化结果。 |
| 服务端 | 单进程服务端，单 SQLite 数据库。 |
| Dashboard | 展示待处理消息、项目风险、用户/账号/项目筛选、采集健康、诊断结果。 |
| 消息 | 初期只支持错误类站内消息。 |
| 诊断 | 初期只支持 `powershell_failure` 和 `shell_failure`。 |

## 项目架构

0.1 架构分为客户端、服务端和 Dashboard。

```text
Codex 本机数据源
  -> agent-observer.exe
  -> 本地状态库 / outbox
  -> HTTP API
  -> 服务端 SQLite
  -> Dashboard
```

### 客户端模块

| 模块 | 职责 |
| --- | --- |
| `EnvironmentDetector` | 自动发现 Codex home、SQLite、rollout、logs、history、auth、installation id。 |
| `CodexAdapter` | 读取 Codex 本机数据源，生成统一事件。 |
| `IdentityCollector` | 生成 terminal user、device、Codex account 的 stable key 和展示名候选。 |
| `ProjectResolver` | 从 cwd、Git root、Git remote、repo name 生成 project key 和展示名候选。 |
| `LocalStateStore` | 保存本地配置、source cursor、outbox、upload ack、diagnostic job。 |
| `TelemetryBuilder` | 脱敏、分类、生成 event id、构造 telemetry。 |
| `Uploader` | 批量上传 outbox，处理 ack、重试、幂等。 |
| `DiagnosticRunner` | 执行本地白名单诊断模板。 |

### 服务端模块

| 模块 | 职责 |
| --- | --- |
| `Enrollment API` | 注册 collector，签发 collector secret。 |
| `Ingestion API` | 接收 telemetry batch，校验 collector、event id、schema version。 |
| `Heartbeat API` | 接收客户端心跳和采集健康状态。 |
| `Diagnostic API` | 下发白名单诊断任务，接收诊断结果。 |
| `Identity Service` | 管理 terminal user、device、agent account 的 label 和映射。 |
| `Project Service` | 管理 project key、项目展示名、owner team。 |
| `Metric Service` | 聚合 token、thread、错误、工具失败。 |
| `Notification Service` | 根据错误事件生成站内消息。 |
| `Dashboard API` | 提供 Dashboard 查询数据。 |

## 客户端交付

### 发布包

```text
agent-observer-client-windows-x64/
  agent-observer.exe
  config.example.toml
  README.md
  diagnostics/
    powershell_failure.json
    shell_failure.json
  policies/
    default-policy.json
  schemas/
    telemetry.schema.json
    diagnostic-result.schema.json
```

包内不得包含用户数据、服务端长期 token、组织 salt、本机路径。

### 本机运行目录

```text
%LOCALAPPDATA%\AgentObserver\
  config.toml
  agent-observer-state.sqlite
  logs\
    client.log
```

| 路径 | 用途 |
| --- | --- |
| `config.toml` | 服务端地址、组织 id、collector id、采集间隔、隐私开关。 |
| `agent-observer-state.sqlite` | 本地状态库。 |
| `logs\client.log` | 客户端自身日志，不混入 Codex 日志。 |

### 配置

```toml
[server]
base_url = "http://127.0.0.1:8088"
organization_id = "default"

[collector]
collector_id = ""
display_name = ""
collect_interval_seconds = 60
upload_interval_seconds = 30

[privacy]
allow_repo_name_candidate = true
allow_local_alias_upload = true

[agents.codex]
enabled = true
home = "auto"

[diagnostics]
enabled = true
default_level = "D1"
```

0.1 可以把 `collector_secret` 保存在本机状态库中，但不得打印到日志或 `status` 输出中。

## 客户端命令

| 命令 | 0.1 要求 |
| --- | --- |
| `agent-observer.exe run-once` | P0。执行一轮注册检查、环境检测、增量采集、写 outbox、上传、ack 后退出。 |
| `agent-observer.exe start` | P1。前台常驻，循环执行采集、上传、心跳、诊断任务拉取。Ctrl+C 后安全退出。 |
| `agent-observer.exe status` | 输出配置状态、Codex 检测状态、游标、outbox 积压、最近上传结果。 |
| `agent-observer.exe doctor` | 检查本机目录权限、Codex 数据源可读性、服务端连通性、schema version。 |
| `agent-observer.exe preview-upload` | 展示下一批上报字段摘要，不展示原始日志。 |
| `agent-observer.exe diagnose powershell_failure` | 本机执行 PowerShell 失败诊断，生成 D1 结果。 |
| `agent-observer.exe diagnose shell_failure` | 本机执行 shell 失败诊断，生成 D1 结果。 |

## P0/P1 运行状态机

### P0 run-once

```text
load config
  -> ensure local state
  -> enroll if needed
  -> detect Codex environment
  -> retry unacked outbox
  -> collect incremental data once
  -> write outbox
  -> upload outbox batch
  -> save ack
  -> print summary
  -> exit
```

P0 用于验证采集链路，不负责持续采集。

### P1 start

```text
load config
  -> ensure local state
  -> enroll if needed
  -> detect Codex environment
  -> loop until Ctrl+C:
       retry unacked outbox
       collect incremental data
       write outbox
       upload outbox batch
       send heartbeat
       pull diagnostic jobs
       run allowed diagnostics
       upload diagnostic results
       sleep collect_interval_seconds
  -> flush local state
  -> exit
```

P1 必须前台常驻。用户关闭窗口或 Ctrl+C 后停止采集；下次启动依靠 cursor 和 outbox 续采。

### 异常处理

| 异常 | 处理 |
| --- | --- |
| 服务端不可达 | 保留 outbox，退避重试，`status` 显示最近失败原因。 |
| Codex 数据源不存在 | 标记 `source_missing`，继续心跳，不清理已采数据。 |
| SQLite 被锁 | 本轮跳过该数据源，记录 warning，下轮重试。 |
| JSONL offset 超过文件大小 | 标记文件被截断或替换，执行安全重扫。 |
| outbox 积压过多 | 暂停新采集或降低批大小，优先上传未 ack 事件。 |
| 服务端禁用 collector | 停止 telemetry 上传，只显示禁用状态。 |

## Codex 数据源

0.1 只读取以下 Codex 数据源：

| 来源 | 读取内容 |
| --- | --- |
| `state_5.sqlite.threads` | thread id、cwd、model、source、tokens_used、rollout_path、created_at_ms、updated_at_ms。 |
| `sessions\...\rollout-*.jsonl` | `session_meta`、`turn_context`、`token_count`、tool call 类型、tool call 状态、错误类别。 |
| `logs_2.sqlite.logs` | `id`、level、target、message fingerprint、thread_id。 |
| `history.jsonl` | session_id、ts、输入长度；不上传 text 原文。 |
| `auth.json` | 仅本地解析账号 claim 后 hash；不上传 auth 原文、access token、refresh token、API key。 |
| `installation_id` | 本地生成 device key。 |

## 身份与项目

### stable key

```text
terminal_user_key = hash(org_salt + os_user_sid)
device_key = hash(org_salt + installation_id)
agent_account_key = hash(org_salt + codex_account_claim)
project_key = hash(org_salt + normalized_git_remote_or_workspace_root)
```

`org_salt` 由服务端 enrollment 返回，不能硬编码在客户端包内。

### display label

Dashboard 和站内消息默认展示 label，不展示裸 hash。

| 对象 | 0.1 label 来源 |
| --- | --- |
| terminal user | 用户本机确认别名；未绑定显示 `未命名终端用户`。 |
| device | 用户本机确认设备别名；未绑定显示 `未命名设备`。 |
| agent account | 本机确认账号别名；未绑定显示 `未绑定 Codex 账号`。 |
| project | Git remote repo name、用户确认别名或服务端绑定；未绑定显示 `未命名项目`。 |

hash 只出现在详情页技术字段和审计输出中。

## Telemetry 事件

0.1 只支持以下事件类型：

| 事件 | 用途 |
| --- | --- |
| `ClientHeartbeat` | 客户端版本、采集状态、outbox 积压、最近错误。 |
| `AgentEnvironmentDetected` | Codex 环境检测结果。 |
| `IdentityObserved` | terminal user、device、Codex account 的 stable key、label 候选、置信度。 |
| `ProjectObserved` | project key、label 候选、识别来源、置信度。 |
| `ThreadObserved` | thread/session 元数据摘要。 |
| `TokenUsageObserved` | token 时间桶聚合。 |
| `ToolCallObserved` | 工具调用类型、状态、错误类别。 |
| `ErrorObserved` | 错误类别、fingerprint、影响范围。 |
| `DiagnosticQueryResult` | 本地诊断结构化结果。 |

### 通用事件字段

```json
{
  "event_id": "evt_...",
  "event_type": "ErrorObserved",
  "schema_version": "0.1",
  "org_id": "default",
  "collector_id": "col_...",
  "agent_type": "codex",
  "occurred_at": "2026-06-14T10:00:00Z",
  "received_at": "server filled",
  "payload": {}
}
```

`event_id` 由客户端生成，服务端按 `event_id` 幂等写入。

## 本地状态库 schema

### `client_config_state`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | text primary key | 配置项。 |
| `value` | text | 配置值。 |
| `updated_at` | text | 更新时间。 |

### `detected_environments`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | text primary key | 环境 id。 |
| `agent_type` | text | 固定为 `codex`。 |
| `home_path_hash` | text | Codex home 路径 hash。 |
| `status` | text | `detected`、`missing`、`error`。 |
| `capabilities_json` | text | 可用数据源摘要。 |
| `last_detected_at` | text | 最近检测时间。 |

### `source_cursors`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_id` | text primary key | 例如 `codex.threads`、`codex.logs`、`codex.rollout:<thread_id>`。 |
| `cursor_json` | text | 游标内容。 |
| `source_status` | text | `ok`、`missing`、`locked`、`error`。 |
| `updated_at` | text | 最近更新时间。 |

### `outbox_events`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | text primary key | 幂等事件 id。 |
| `event_type` | text | 事件类型。 |
| `payload_json` | text | 已脱敏 telemetry。 |
| `status` | text | `pending`、`uploading`、`acked`、`failed`。 |
| `attempt_count` | integer | 上传尝试次数。 |
| `last_error` | text | 最近错误摘要。 |
| `created_at` | text | 创建时间。 |
| `updated_at` | text | 更新时间。 |

索引：

```sql
create index idx_outbox_status_created on outbox_events(status, created_at);
```

### `upload_acks`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ack_id` | text primary key | 服务端 ack id。 |
| `batch_id` | text | 上传批次 id。 |
| `acked_event_count` | integer | 确认数量。 |
| `server_time` | text | 服务端时间。 |
| `created_at` | text | 本地记录时间。 |

### `diagnostic_jobs`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `job_id` | text primary key | 服务端诊断任务 id 或本地任务 id。 |
| `template` | text | `powershell_failure` 或 `shell_failure`。 |
| `scope_json` | text | 时间窗、项目、用户等范围。 |
| `status` | text | `pending`、`running`、`completed`、`rejected`、`failed`。 |
| `result_json` | text | D1 结构化结果。 |
| `created_at` | text | 创建时间。 |
| `updated_at` | text | 更新时间。 |

## 服务端 API

0.1 API 使用 JSON over HTTP。

所有需要认证的请求带：

```text
Authorization: Collector <collector_id>:<signature>
```

0.1 使用 `collector_secret` 计算 HMAC。

### `POST /api/collectors/enroll`

注册 collector。

请求：

```json
{
  "organization_id": "default",
  "enrollment_code": "code",
  "client_version": "0.1.0",
  "device_label": "张三的 Windows 工作站"
}
```

响应：

```json
{
  "collector_id": "col_123",
  "collector_secret": "secret",
  "org_salt": "salt",
  "server_time": "2026-06-14T10:00:00Z",
  "capabilities": {
    "schema_version": "0.1",
    "max_batch_size": 200
  }
}
```

### `GET /api/capabilities`

返回服务端支持的 schema、采集策略、诊断模板。

### `POST /api/telemetry/batch`

上传 telemetry。

请求：

```json
{
  "batch_id": "batch_123",
  "schema_version": "0.1",
  "collector_id": "col_123",
  "events": []
}
```

响应：

```json
{
  "batch_id": "batch_123",
  "accepted_event_ids": [],
  "duplicate_event_ids": [],
  "rejected": [],
  "server_time": "2026-06-14T10:00:00Z"
}
```

服务端必须按 `event_id` 去重。客户端收到 accepted 或 duplicate 都可以将事件标记为 `acked`。

### `POST /api/collectors/heartbeat`

上报客户端健康状态。

请求字段至少包含：

```json
{
  "collector_id": "col_123",
  "client_version": "0.1.0",
  "status": "running",
  "outbox_pending": 12,
  "last_collect_at": "2026-06-14T10:00:00Z",
  "last_upload_at": "2026-06-14T10:00:00Z",
  "last_error": ""
}
```

### `GET /api/diagnostic-jobs/pull`

客户端拉取自己的诊断任务。0.1 可以返回空数组，也必须实现接口。

### `POST /api/diagnostic-results`

上传 D1 诊断结果。

## 服务端 SQLite schema

### 核心表

```sql
create table collectors (
  collector_id text primary key,
  organization_id text not null,
  collector_secret_hash text not null,
  display_label text,
  status text not null,
  client_version text,
  created_at text not null,
  updated_at text not null
);

create table telemetry_events (
  event_id text primary key,
  organization_id text not null,
  collector_id text not null,
  event_type text not null,
  schema_version text not null,
  occurred_at text not null,
  received_at text not null,
  payload_json text not null
);

create table terminal_users (
  terminal_user_key text primary key,
  display_label text,
  confidence text,
  updated_at text not null
);

create table devices (
  device_key text primary key,
  collector_id text not null,
  display_label text,
  updated_at text not null
);

create table agent_accounts (
  agent_account_key text primary key,
  provider text not null,
  display_label text,
  confidence text,
  updated_at text not null
);

create table projects (
  project_key text primary key,
  display_label text,
  source text,
  confidence text,
  owner_team text,
  updated_at text not null
);

create table metric_rollups (
  rollup_id text primary key,
  bucket_start text not null,
  bucket_size text not null,
  metric_name text not null,
  dimensions_json text not null,
  value real not null,
  updated_at text not null
);

create table diagnostic_results (
  result_id text primary key,
  job_id text,
  collector_id text not null,
  template text not null,
  scope_json text not null,
  result_json text not null,
  created_at text not null
);

create table notification_inbox (
  message_id text primary key,
  recipient_type text not null,
  recipient_id text not null,
  recipient_label text,
  severity text not null,
  category text not null,
  title text not null,
  summary text not null,
  status text not null,
  source_event_ids_json text,
  created_at text not null,
  updated_at text not null
);

create table collector_acks (
  ack_id text primary key,
  collector_id text not null,
  batch_id text not null,
  acked_event_count integer not null,
  created_at text not null
);
```

### 必要索引

```sql
create index idx_events_org_type_time on telemetry_events(organization_id, event_type, occurred_at);
create index idx_rollups_metric_bucket on metric_rollups(metric_name, bucket_start);
create index idx_notifications_recipient_status on notification_inbox(recipient_type, recipient_id, status);
create index idx_collectors_status on collectors(status);
```

## 采集与续采

### 游标

| 数据源 | 游标 |
| --- | --- |
| `state_5.sqlite.threads` | `(updated_at_ms, id)`，首次回填另用 `(created_at_ms, id)`。 |
| `logs_2.sqlite.logs` | `id`。 |
| rollout JSONL | `(thread_id, rollout_path, byte_offset, line_index, last_event_timestamp)`。 |
| `history.jsonl` | `(byte_offset, line_index, last_ts, session_id)`。 |

### 首次回填

首次运行从可发现的最早 Codex 数据开始：

1. 枚举 `state_5.sqlite.threads`。
2. 读取每个 thread 的 `rollout_path`。
3. 从 rollout 文件头开始提取 token、tool call、错误类别。
4. 读取 `logs_2.sqlite.logs` 的 WARN/ERROR 摘要。
5. 读取 `history.jsonl` 的 session_id、ts、输入长度。
6. 写入 outbox。
7. 上传后记录 ack。

### event id

```text
ThreadObserved = hash(collector_id + "thread" + thread_id + updated_at_ms)
ToolCallObserved = hash(collector_id + "rollout" + thread_id + line_index + payload_hash)
ErrorObserved = hash(collector_id + "error" + source + source_id + fingerprint)
TokenUsageObserved = hash(collector_id + "token" + bucket + dimensions_hash)
```

## 隐私边界

### 默认允许

- 数字指标。
- 枚举字段。
- 时间桶。
- hash 后的用户、设备、账号、项目、thread id。
- 用户确认或服务端绑定的 display label。
- 模型名、Agent 类型、客户端版本。
- 错误类别、fingerprint、exit code。
- 工具类型、状态。
- D1 诊断结构化结果。

### 默认禁止

- prompt 原文。
- assistant 回复原文。
- tool output 原文。
- stderr 原文。
- shell command 完整参数。
- 文件内容。
- rollout JSONL 原文。
- auth 文件原文。
- access token、refresh token、API key、cookie。
- 绝对路径明文。

## 诊断

0.1 只支持 D1 级别诊断。

| 模板 | 本地查询 | 上报 |
| --- | --- | --- |
| `powershell_failure` | rollout tool event、exit code、PowerShell 错误类别。 | 时间桶、错误类别、exit code、thread key、project key、计数。 |
| `shell_failure` | shell tool event、exit code、错误类别。 | 时间桶、错误类别、exit code、thread key、project key、计数。 |

服务端不能下发任意 SQL、任意 grep、任意 shell、任意文件读取。诊断任务只能来自内置模板。

## 站内消息

0.1 只生成错误消息。

触发条件：

```text
ErrorObserved
或 ToolCallObserved.status = failed
或 DiagnosticQueryResult.result = failed_exists
```

去重规则：

```text
recipient + project_key + category + fingerprint + 24h time window
```

消息字段：

| 字段 | 说明 |
| --- | --- |
| `message_id` | 消息 id。 |
| `recipient_type` | `terminal_user`、`agent_account`、`project`。 |
| `recipient_id` | stable key。 |
| `recipient_label` | 可读展示名。 |
| `severity` | `warning`、`error`、`critical`。 |
| `category` | `shell_failure`、`powershell_failure`、`collector_issue`。 |
| `title` | 不含敏感原文的标题。 |
| `summary` | 不含原始日志的摘要。 |
| `status` | `unread`、`read`、`handled`、`ignored`。 |

推荐标题：

```text
uDSP / pm_udsp 出现 5 次 PowerShell ParserError
张三的 Codex Pro 在 Agent Observer 中出现 shell_failure
```

## Dashboard

0.1 Dashboard 第一屏必须回答四个问题：

| 问题 | 展示 |
| --- | --- |
| 现在谁需要处理 | 未读错误消息、接收人、项目、严重级别、建议动作。 |
| 哪些项目风险最高 | 项目错误数、token、失败工具分布、owner team。 |
| 哪些用户/账号异常 | 用户 token、错误集中度、账号识别状态。 |
| 数据是否可信 | collector 在线状态、outbox 积压、未绑定用户/项目。 |

默认展示 display label，不展示裸 hash。未绑定时显示 `未命名终端用户`、`未命名项目`，并出现在待绑定列表中。

## 服务端查询 API

Dashboard 至少需要以下查询：

```text
GET /api/dashboard/summary
GET /api/dashboard/messages
GET /api/dashboard/projects
GET /api/dashboard/collectors
GET /api/dashboard/diagnostics
```

查询参数：

```text
from
to
terminal_user_key
agent_account_key
project_key
collector_id
```

## 0.1 验收标准

### 客户端验收

- 用户下载 zip 后无需安装开发环境即可运行。
- `run-once` 能自动检测本机 Codex 环境。
- `run-once` 能生成本地状态库。
- `run-once` 能从 Codex 数据源提取 thread、token、tool call、错误摘要。
- `run-once` 能写入 outbox 并上传服务端。
- 重复运行 `run-once` 不重复计数。
- `start` 能前台常驻并按间隔持续采集。
- `start` 被 Ctrl+C 停止后，下次启动能续采。
- `status` 能显示检测状态、游标、outbox、最近上传结果。
- `doctor` 能检查本地权限、Codex 数据源、服务端连通性。
- `preview-upload` 不显示原始日志、prompt、stderr、auth 原文。

### 服务端验收

- 能完成 collector enrollment。
- 能接收 telemetry batch。
- 能按 event id 幂等写入。
- 能保存 terminal user、device、agent account、project 映射。
- 能生成 token、thread、错误 rollup。
- 能生成错误站内消息。
- 能接收 D1 诊断结果。
- Dashboard 能展示 summary、messages、projects、collectors、diagnostics。

### 隐私验收

- 服务端数据库中不存在 prompt 原文。
- 服务端数据库中不存在 assistant 回复原文。
- 服务端数据库中不存在 tool output 原文。
- 服务端数据库中不存在 auth 原文、access token、refresh token、API key。
- Dashboard 主视图不以裸 hash 作为用户或项目名称。

## 开发顺序

1. 建服务端 SQLite schema 和 enrollment / telemetry batch API。
2. 建 Go CLI 骨架和本地状态库。
3. 实现 Codex 环境检测。
4. 实现 `run-once` 的 threads、rollout、logs 读取。
5. 实现 outbox、event id、上传、ack。
6. 实现服务端入库、rollup、错误消息。
7. 实现 `start` 前台常驻循环。
8. 实现 `status`、`doctor`、`preview-upload`。
9. 实现 `powershell_failure`、`shell_failure` 诊断。
10. 接入 Dashboard 查询。
