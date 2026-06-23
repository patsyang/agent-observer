# 多 Agent 统一采集生产规格

## Product Outcome

用户能在 agent-observer 中用统一方式观察 Codex 与 WorkBuddy 的本机会话、工具调用、风险、用量和采集状态。

## Domain Objects and States

- Collector：`online`、`degraded`、`offline`。
- Agent Source：`online`、`degraded`、`offline`、`source_missing`、`source_locked`。
- Observed Fact：`agent_prompt`、`agent_response`、`agent_reasoning`、`tool_call`、`tool_result`、`model_usage`、`file_change`、`destructive_operation`、`sensitive_content_exposure`、`uncategorized`。
- Conversation：按 `conversation_ref/session_ref/source_path_hash` 聚合，按通用 prompt category 切分 turn。
- Risk Signal：只依赖通用 fact/risk 类型，不依赖 Agent 原生字段。

## Backend and Data Contracts

- 新增 `agent_sources` 表，表示一个 collector 下的具体 Agent 来源。
- telemetry v3 batch 必须包含 `source_id`、`agent_type`、`source_kind`。
- `observed_facts` 存储 `source_id`、`agent_type`、`source_kind`、`normalized_event_type`。
- `source_specific_json` 仅保存原生源字段，不作为业务规则主判断依据。
- 默认保留原文上传，`evidence_projections.raw_content` 继续用于前端原文观察。

## Collector Contract

客户端 source module 必须实现：

- source discovery
- incremental cursor
- source-specific parsing
- normalized fact mapping
- source capabilities

本期 source：

- `codex_local`：读取 `.codex/sessions` 和 session index。
- `workbuddy_local`：读取 `.workbuddy/sessions`、`traces`、`audit-log`、`tasks`、`projects`。

## Frontend Product Surface

- 采集器页展示 collector 与其 source 列表。
- Dashboard 展示多 source 总览，并提供 Agent/source/workspace 筛选。
- 会话查询展示 Agent/source，支持按 Agent/source 过滤。
- 信号详情继续展示原文证据、工具上下文和来源信息。

## Release Gates

- 后端 pytest 覆盖 v3 ingest、source 状态、Codex 与 WorkBuddy fixtures。
- 前端 Vitest 覆盖多 source 展示与筛选。
- Playwright 覆盖下载包、运行 packaged collector、Dashboard、Collectors、Conversations 和 Signal 操作。
- 最终使用 sub agent 执行审查式 Review，并修复发现的问题。
