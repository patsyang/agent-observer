# 工作流控制平面架构

## 分层

```text
Workflow Definition      .agentic/workflow/definitions/*.json
Workflow Contract        .agentic/workflow/*.md
Control Plane            tools/workflow_runner/
Python Entrypoint        scripts/ao.py
斜杠命令                commands/*.md
Codex Skill             .codex/skills/*/SKILL.md
Runtime Adapter          tools/workflow_runner/.../adapters/
Artifacts                ai_docs/runs/<run_id>/
Verification             python scripts/ao.py verify
Business Code            apps/<app>/
```

## 职责

| 层 | 职责 | 不负责 |
| --- | --- | --- |
| Definition | 给工具读取的结构化工作流定义 | 解释业务需求 |
| Contract | 给用户和 Agent 读取的工作流契约 | 执行命令 |
| Control Plane | 参数校验、run_id、事件日志、报告、验证 | 调用模型自动写代码 |
| 斜杠命令 | 暴露 `/ao-spec`、`/ao-plan`、`/ao-small`、`/ao-infra` 等用户入口 | 复制控制平面逻辑 |
| Codex Skill | 承载命令对应的执行细则 | 决定底层事件和报告格式 |
| Runtime Adapter | 将 Codex、Trae、Claude 或三方 CLI 接入统一产物格式 | 决定工作流规则 |
| Business Code | 实现具体业务应用能力 | 管理开发工作流 |

## 为什么不直接用第三方引擎

第三方工作流可以接入，但不能决定项目治理口径。项目需要稳定的输入、日志、产物和隐私边界，供未来统一可观测性使用。

## 扩展点

新增工作流：

1. 新增 `.agentic/workflow/definitions/<workflow>.json`。
2. 新增 `.agentic/workflow/<workflow>.md`。
3. 如需第三方执行，新增适配器说明并遵守 `.agentic/workflow/adapter-contract.md`。
4. 增加 dry-run 或 fixture 级测试。

新增适配器：

1. 在 adapter registry 中注册稳定名称，例如 `codex`、`trae`、`claude`。
2. 保持标准输入参数不变。
3. 输出 `workflow-event.jsonl` 和 `run-report.md`。
4. 不上传原始 prompt、token、auth 或日志正文。
5. 用 fake executable 或 fixture 做测试，不依赖真实用户账号。

## Codex 与 Python 入口

Codex 交互式运行依赖项目斜杠命令：

```text
commands/<command>.md  -> command 文件内声明的 .codex/skills/<skill>/SKILL.md
```

在 Codex 中直接输入 `/ao-spec`、`/ao-plan`、`/ao-small` 或 `/ao-infra`。

Python 非交互运行依赖 runtime adapter：

```text
python scripts/ao.py codex-adapter `
  --workflow plan-execute `
  --goal "..."
```

二者共享同一套 workflow definition、contract、run artifacts 和验证门禁。

## 多项目复用

本仓库内的 `tools/workflow_runner` 按可抽离基础设施维护。多项目复用设计见 `.agentic/workflow/multi-project-infra.md`。
