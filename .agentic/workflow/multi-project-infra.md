# 多项目 Agentic Coding 基础设施设计

## 问题

Agentic Factory 需要高质量 Agentic Coding 工作流，但这套能力不应只服务当前项目。以后多个项目都需要复用同一套工作流治理、运行记录、日志事件、验证门禁和第三方工作流接入能力。

因此需要把能力分成两层：

```text
业务项目层：agentic_factory、其他业务项目
基础设施层：agentic coding control plane
```

## 当前落点

当前第一版基础设施暂放在本仓库：

```text
tools/workflow_runner/
scripts/ao.py
.agentic/workflow/
ai_docs/runs/
```

这是为了快速验证架构，不表示它永远属于 Agentic Factory。它的代码和契约要按“可抽离”标准维护。

## 目标形态

未来应演进为一个可复用基础设施包：

```text
agentic-coding-infra/
  runner/                 # 控制平面 CLI 或库
  adapters/               # codex / claude / trae / swfac / custom-command
  workflow-definitions/   # 标准工作流定义
  templates/              # AGENTS、.agentic/workflow、ai_docs 模板
  schema/                 # workflow event、run report、input 参数 schema
  docs/
```

业务项目只保留项目侧配置和产物：

```text
some-project/
  AGENTS.md
  .agentic/workflow/
    workflow-governance.md
    definitions/
    <workflow>.md
  ai_docs/
    specs/
    goals/
    plans/
    runs/
  scripts/
    ao.py                 # Python 主入口，调用基础设施 CLI
  apps/
    <app>/
      backend/
      frontend/
      collector/
      e2e/
```

## 分层职责

| 层 | 归属 | 职责 |
| --- | --- | --- |
| Workflow Schema | 基础设施 | 标准参数、事件、报告格式 |
| Workflow Runner | 基础设施 | run_id、参数校验、事件日志、报告、超时和进程树清理 |
| Adapter | 基础设施或项目 | 接入本地 Agent、三方 CLI、远程工作流服务 |
| Workflow Definition | 基础设施 + 项目覆盖 | 定义工作流名称、输入、阶段、验证策略 |
| Workflow Contract | 项目 | 描述项目内如何执行该工作流 |
| Verify Gate | 项目 | 由项目决定测试和 e2e，通过 `python scripts/ao.py verify` 暴露 |
| Business Code | 项目 | `apps/<app>/` 下的后端、前端、collector 等业务实现 |

## 核心原则

- 基础设施不理解业务代码。
- 基础设施不决定用户该选哪个工作流。
- 项目必须显式声明可用工作流。
- 项目必须提供自己的验证入口。
- 第三方工作流只能通过 adapter 接入，不能绕过统一日志和运行报告。
- 可观测性只依赖标准事件和报告，不依赖某个工作流引擎内部结构。

## 统一接口

所有项目都应支持同类 Python 入口：

```text
python scripts/ao.py workflow list
python scripts/ao.py workflow prepare --workflow <name> ...
python scripts/ao.py workflow execute --workflow <name> --adapter <runtime> ...
python scripts/ao.py workflow complete --workflow <name> --run-id <id> ...
```

标准事件：

```json
{
  "timestamp": "2026-06-14T00:00:00Z",
  "run_id": "run_xxx",
  "workflow": "plan-execute",
  "step": "verify",
  "status": "passed",
  "message": "verification completed",
  "artifact_path": "ai_docs/runs/run_xxx/run-report.md",
  "duration_ms": 12345
}
```

## 第三方工作流接入

第三方工作流包括但不限于：

- swfac
- Superpowers 风格流程
- Claude Code command/skill
- Codex 自定义 workflow
- Trae / Trae CN 自动化流程
- 公司内部 workflow 服务

接入方式：

```text
第三方执行器
  -> adapter
  -> 标准 input.json
  -> workflow-event.jsonl
  -> run-report.md
  -> 项目 verify gate
```

第三方可以负责实现，但不能改变项目侧治理要求。

## 当前项目的下一步演进

短期：

- 保持 `tools/workflow_runner` 在本仓库内。
- 用它支撑 Agentic Factory 的实际开发。
- 通过 `agentic-infra/manifest.json` 声明可复用基础设施文件。
- 通过 `agentic.lock.json` 记录项目已安装的基础设施基线。
- 通过初始化命令创建新项目骨架，不复制当前项目业务代码。
- 通过升级 dry-run 识别 `unchanged`、`would_update`、`local_modified`、`conflict`。

第一版已支持：

```text
python scripts/ao.py agentic-init-project `
  --target D:\workspace\new_project `
  --project-name "New Project"

python scripts/ao.py agentic-update `
  --project-root D:\workspace\new_project `
  --infra-root D:\workspace\agentic_factory
```

升级命令只生成计划，不自动覆盖文件。项目文件和 infra 模板同时变化时标记为
`conflict`，由开发者或 Agent 明确合并。

中期：

- 将 `tools/workflow_runner` 抽成独立 Python 包或内部模板。
- 为新项目提供初始化命令。
- 支持项目级 workflow definition 覆盖。

长期：

- 增加服务端汇总多个项目的工作流运行记录。
- 将 workflow 运行事件纳入 Agentic Factory 自身观测对象。
- 支持按项目、用户、工作流、Agent、失败类型做统一可观测分析。
