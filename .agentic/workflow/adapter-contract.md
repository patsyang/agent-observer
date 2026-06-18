# Agent Runtime 适配器契约

## 定位

适配器负责把不同 Agent 基础设施接入当前项目的统一工作流治理层。
工作流定义回答“做什么流程”，适配器回答“由哪个 Agent runtime 执行”。

## 必须遵守

- 接收标准输入参数：`workflow`、`goal`、`goal_path`、`spec_path`、`plan_path`、`run_id`。
- 写入标准运行目录：`ai_docs/runs/<run_id>/`。
- 写入 `workflow-event.jsonl`。
- 写入 `run-report.md`。
- 不把原始 prompt、token、auth、日志正文写入可上传观测事件。

## 架构边界

```text
workflow definition
  -> project .agentic/project.json
  -> run context
  -> agent runtime adapter
  -> standard artifacts
  -> verification/report
```

适配器不得改变工作流契约，不得绕过 `tools/workflow_runner` 直接自造运行目录。
Codex、Trae、Claude 或第三方 CLI 都必须接入同一套输入、事件和报告。

业务项目的 runtime adapter 只允许来自目标项目的 `.agentic/project.json`。
`workflow run`、`/ao-spec`、resume 和验证必须复用该配置；缺失或无效时立即失败。
不允许 fallback 到默认 Codex，也不允许单次运行临时覆盖目标项目 runtime adapter。

## Runtime Adapter 类型

| 类型 | 状态 | 含义 |
| --- | --- |
| `codex` | 已实现 | 通过 `codex exec` 执行当前工作流 |
| `trae` | 预留 | 通过 Trae/Trae CN 的命令或协议执行 |
| `claude` | 预留 | 通过 Claude Code 或等价命令执行 |
| `external-command` | 预留 | 任意第三方 CLI 工作流桥接 |
| `remote-service` | 预留 | 远程工作流服务 API 桥接 |

## 最小生命周期

```text
prepare -> adapter execute -> complete -> verify -> report
```

E2E workflow 的节点级生命周期：

```text
prepare -> create node context -> adapter execute_node -> artifact gate -> next node
```

`execute_node` 必须接收 `RunContext`、`node_id`、节点定义、worktree 路径、运行产物目录和 required artifacts。适配器负责把这些上下文封装成目标 runtime 的非交互命令，并通过标准环境变量传递给 runtime。Workflow runner 只负责调度、artifact gate、production gate 和报告，不得把 `adapter.command` 当作节点 provider 直接执行。

## 当前 Codex Adapter

Python 入口：

```text
python scripts/ao.py codex-adapter `
  --workflow plan-execute `
  --goal "实现客户端 outbox 上传"
```

底层执行：

```text
tools/workflow_runner execute --adapter codex
```

Codex adapter 只负责调用 Codex runtime，不拥有 `small-change`、`plan-execute`
或 `spec-driven` 的业务规则。节点执行必须使用 `codex exec --cd <worktree>
--output-last-message <path> <prompt>` 形态；项目配置中的 `adapter.command`
只表示 Codex 可执行文件及固定前缀，不是完整节点 provider 命令。

项目配置示例：

```json
{
  "adapter": {
    "id": "codex",
    "command": ["codex.cmd"]
  },
  "verify": {
    "command": ["python", "scripts/verify.py"]
  }
}
```

## 新增 Adapter 要求

新增 Trae、Claude 或三方适配器时必须：

- 在 `tools/workflow_runner/src/agentic_workflow/adapters/` 中实现 adapter。
- 通过 adapter registry 暴露稳定名称。
- 使用标准 `RunContext`。
- 写入 adapter 阶段事件，例如 `adapter:trae`。
- 失败时写入可复盘报告，但不继续执行验证。
- 测试中使用 fake executable 或 fixture，不依赖真实用户环境。
