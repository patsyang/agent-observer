# 多 Agent 统一采集 PRD

## 目标

agent-observer 要从 Codex 单一采集器升级为多 Agent 本机观察台。本期接入 Codex 与 WorkBuddy，让用户能在同一套界面中观察会话原文、工具调用、风险信号、用量、工作区和采集状态。

## 用户与场景

- 本机同时使用 Codex、WorkBuddy 等 Agent 的开发者。
- 需要复盘 Agent 会话、查看工具失败、定位高风险操作和统计 token 用量的人。
- 需要确认采集器是否正常发现本机 Agent 数据源的人。

## 业务对象

- Collector：安装在本机的采集客户端实例。
- Agent Source：Collector 发现的单个 Agent 数据源，例如 `codex_local` 或 `workbuddy_local`。
- Agent Session：一次 Agent 会话或任务上下文。
- Observed Fact：从源事件归一后的可观察事实。
- Conversation：由 prompt、response、tool、risk 和 usage facts 组成的可查询会话。
- Risk Signal：由事实聚合出的风险信号。
- Usage Signal：由模型用量事实产生的统计信号。
- Evidence Projection：事实的可读证据投影，保留默认原文上传。

## 主流程

1. 用户下载并安装 Windows collector。
2. collector 发现本机 Codex 与 WorkBuddy source。
3. collector 分别增量读取各 source 数据，映射为统一事实。
4. collector 默认上传结构化投影与原文证据。
5. 服务端入库并更新会话、用量、风险信号。
6. 用户在前端按 Agent/source/workspace/time 查询会话。
7. 用户查看风险信号详情并处理信号。

## 非目标

- 本期不接入 Trae CN。
- 不保留旧 v2 协议、旧 DB 或旧客户端兼容。
- 不做云端多租户。
- 不新增 Agent 专属 API、页面或业务规则。

## 验收标准

- 一个 collector 可以同时报告 Codex 与 WorkBuddy source。
- Codex 与 WorkBuddy 都能产生通用 prompt、response、tool、usage、risk facts。
- 前端能按 Agent/source 过滤并查看原文证据。
- 新增第三类 Agent 时，只需要新增 source module 与 fixture，不需要改后端业务 API 或前端业务页面模型。
