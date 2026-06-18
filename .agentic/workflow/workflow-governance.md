# 工作流治理规范

## 目标

当前项目的开发流程必须支持多个工作流共存，并为未来统一可观测性保留一致的输入、日志、产物和验证结构。

## 架构边界

```text
用户选择 workflow + 参数
  -> python scripts/ao.py
  -> tools/workflow_runner
  -> 项目注册表解析目标 repo_root
  -> .agentic/workflow/definitions/*.json
  -> .agentic/workflow/<workflow>.md
  -> ai_docs/runs/<run_id>/ 或目标项目 runtime.runs_dir/<run_id>/
```

`tools/workflow_runner` 是项目内工作流控制面和 E2E 执行内核。它负责参数校验、scope 解析、worktree 隔离、节点调度、产物门禁、运行报告和验证命令。

真正的实现动作由当前 Agent、未来第三方 CLI 或远程工作流服务通过节点适配器完成，但 workflow runner 必须拥有节点状态、required artifacts、acceptance matrix、生产级 evidence gate 和 resume 指针。

Codex、Trae、Claude 等基础设施不直接改变工作流规则。它们只作为
runtime adapter 接入统一控制平面。

## 基本原则

- 用户显式选择工作流；Agent 不自动路由。
- 工作流只通过参数控制，不通过临时口头约定控制。
- 每个工作流必须有契约文档，说明输入、产物、日志、验证和失败处理。
- 所有工作流都必须写运行报告，便于后续观测、审计和复盘。
- 新工作流接入时不得破坏既有工作流参数和产物格式。

## 标准输入参数

| 参数 | 含义 |
| --- | --- |
| `workflow` | 工作流名称，例如 `small-change`、`plan-execute`、`spec-driven` |
| `goal` | 一次性自然语言目标 |
| `goal_path` | Goal 文件路径，通常位于 `ai_docs/goals/` |
| `spec_path` | Spec 文件路径，业务规格通常位于 `apps/<app>/specs/`，临时输入可位于 `ai_docs/specs/` |
| `plan_path` | Plan 文件路径，通常位于 `ai_docs/plans/` |
| `scope` | 显式工作边界，例如 `apps/agentic_factory`、`control-plane` |
| `project` | 已注册业务项目名，用于把 workflow 目标切到业务仓库 |
| `project_root` | 一次性业务项目仓库路径；长期项目应使用 `project` |
| `run_id` | 单次运行 ID；没有时由执行方生成 |

同一次运行只允许使用一种主输入：`goal`、`goal_path`、`spec_path`、`plan_path` 四选一，除非工作流契约明确允许组合。`scope`、`project` 和 `project_root` 不是主输入；`project`/`project_root` 选择目标仓库，`scope` 只约束该仓库内写入边界。

## 标准产物

```text
ai_docs/
  specs/      临时或跨项目规格输入
  goals/      单次任务输入
  plans/      已确认实施计划
  runs/       单次运行报告
```

控制面 workflow 每次运行还必须写入：

```text
ai_docs/runs/<run_id>/
  run.json
  artifacts/
  nodes/
  acceptance-matrix.json
  workflow-event.jsonl
  run-report.md
```

业务项目 workflow 每次运行写入目标项目 `.agentic/project.json` 的
`runtime.runs_dir`，隔离 worktree 写入 `runtime.worktrees_dir`，日志写入
`runtime.logs_dir`。缺省值分别是 `.agentic/runs`、`.agentic/worktrees` 和
`.agentic/logs`。

运行报告必须包含：

- `run_id`
- `workflow`
- 目标项目和 `project_root`
- 输入参数
- 修改摘要
- 变更文件
- 验证命令和结果
- 产物路径
- 风险和后续动作

## 统一日志事件

所有工作流日志、运行报告和未来服务端观测事件都应使用以下字段：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 本地事件时间 |
| `run_id` | 单次运行 ID |
| `workflow` | 工作流名称 |
| `step` | 当前阶段，例如 `spec`、`plan`、`test`、`e2e` |
| `status` | `started`、`passed`、`failed`、`skipped` |
| `message` | 人类可读摘要 |
| `artifact_path` | 相关产物路径 |
| `duration_ms` | 阶段耗时 |

日志不得包含原始 prompt、原始日志、token、auth 文件内容或完整命令输出中的敏感信息。

## 工作流契约

每个工作流需要两份文件：

```text
.agentic/workflow/
  definitions/<workflow>.json
  small-change.md
  plan-execute.md
  spec-driven.md
```

`definitions/*.json` 给工具读取，契约 Markdown 给 Agent 和用户读取。

契约文件必须说明：

- 适用场景
- 必需参数
- 可选参数
- 运行阶段
- 节点产物
- 必须产物
- 验证门禁
- 失败后如何恢复

## 新工作流接入要求

新增工作流时必须先补：

- `.agentic/workflow/definitions/<workflow>.json`
- 契约文档
- 输入参数说明
- 运行报告模板变化
- 日志字段映射
- 至少一个 dry-run 或 fixture 级验证方式

如果未来接入 `swfac` 或其他三方工作流，本规范仍然作为 Agentic Factory 的项目侧治理契约。

多项目复用和基础设施抽离设计见 `.agentic/workflow/multi-project-infra.md`。

## 本地控制命令

列出工作流：

```text
python scripts/ao.py workflow list
```

启动一次完整运行：

```text
python scripts/ao.py workflow run `
  --workflow plan-execute `
  --project app-a `
  --goal "实现客户端 outbox 上传"
```

注册业务项目：

```text
python scripts/ao.py project register --name app-a --root D:\workspace\apps\app-a
python scripts/ao.py project stack profiles
python scripts/ao.py project list
python scripts/ao.py project status app-a
```

查看与恢复运行：

```text
python scripts/ao.py workflow status --run-id run_xxx
python scripts/ao.py workflow resume --run-id run_xxx
python scripts/ao.py workflow cleanup --run-id run_xxx
```

## 斜杠命令封装

项目提供以下面向 Codex 的斜杠命令：

```text
commands/<command>.md      -> command 文件内声明 skill 和 workflow
```

斜杠命令只负责解析用户入口、固定 workflow 名称和约束输入参数，
不允许复制或绕过 `python scripts/ao.py` 和 workflow runner 的治理逻辑。

## Runtime Adapter

Codex 内部交互式使用项目斜杠命令：

```text
/ao-spec <项目名> -prd <PRD路径>
/ao-spec <项目名> -spec <规格路径>
/ao-spec <项目名> -plan <计划路径>
/ao-plan <目标|goal_path|spec_path|plan_path>
/ao-plan --project <项目名> <目标>
/ao-small <明确的小目标>
/ao-small --project <项目名> <明确的小目标>
/ao-infra <明确的控制面修改目标>
```

命令契约和 skill 映射以 command 文件为准：

```text
commands/<command>.md
```

Python 非交互执行使用 Codex adapter：

```text
python scripts/ao.py codex-adapter `
  --workflow plan-execute `
  --goal "实现客户端 outbox 上传"
```

业务 workflow 运行链路：

```text
project-config -> scope-resolve -> create-worktree -> nodes -> artifact-gates -> evidence-gates -> acceptance-gate -> verify -> report
```

业务 workflow 必须读取目标项目 `.agentic/project.json` 中的 runtime adapter 和
`verify.command`。项目 adapter 是项目生命周期配置，不是每次运行的临时参数。
缺失 adapter、adapter command 不可解析或 verify command 缺失时必须失败。
节点执行必须调用已注册 runtime adapter 的 node-level 接口，由 adapter 封装
`codex exec`、工作目录、运行产物和输出消息；不得把 `adapter.command` 当作节点
provider 直接执行。不得 fallback 到默认 Codex，不得单次运行临时覆盖目标项目
runtime adapter。

新增 Trae、Claude 或三方 adapter 时，只允许接入 `RunContext` 和标准运行目录，
不允许复制 workflow 规则或绕过本规范。
