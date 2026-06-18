---
name: ao-small
description: 处理当前项目的小修复、小配置、小 UI 调整或低风险 bug 时使用。对应 small-change E2E 工作流。
---

# ao-small

本 Skill 服务 `/ao-small` 命令，执行 `small-change` E2E 工作流。它只处理局部小修，核心是 repro/scope/verification gate，不是短 plan。

## 触发场景

- 用户要求修复一个明确的小 bug。
- 用户要求调整文案、样式、配置或脚本细节。
- 改动范围很小，不需要重新设计规格。
- 修改不跨多个组件，不改变数据模型、隐私、安全、产品能力或长期验收。

## 输入

命令后的内容应是明确目标，也可以带已注册业务项目：

```text
/ao-small 修复首页状态文案显示不完整
/ao-small --project app-a 修复 Dashboard 未读消息数量显示不更新
```

长期业务项目使用 `--project <name>`；一次性目标仓库可使用 `--project-root <path>`。
`scope` 只用于目标仓库内显式写入边界，或 `agentic-infra`、`control-plane`、`repo`。

## 执行规则

1. 全程使用中文输出。
2. 读取 `AGENTS.md`。
3. 读取 `commands/ao-small.md`。
4. 读取 `.agentic/workflow/workflow-governance.md`。
5. 读取 `.agentic/workflow/small-change.md`。
6. 读取 `.agentic/workflow/definitions/small-change.json`。
7. 业务项目运行前必须能读取 confirmed `.agentic/stack-contract.json`；缺失时停止并要求先确认项目级技术栈契约。
8. 使用 `python scripts/ao.py small-change run --project <项目名> --goal <目标>` 启动业务项目完整运行。
9. 读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
10. workflow 必须完成 small-scope gate、repro-or-signal、隔离 worktree、最小实现、定向验证、独立审查、小修验收 gate 和 run-report.md。
11. workflow 必须生成并校验 `repro.md`、`small-scope.json`、`verification.json`。
12. `/ao-small` 不生成 `plan.md`、`tasks.json` 或 `task-graph.json`。
13. 最终必须产出带同一 `stack_contract_ref` 的 `acceptance-matrix.json`、`component-evidence.json`、`command-coverage.json`。
14. 目标项目不唯一时停止，要求用户使用 `--project`。
15. Bug 修复必须先补回归测试；无法自动测试的纯文档、纯配置或纯样式改动必须说明替代验证。
16. 完成后运行受影响测试；同一失败最多修复 3 次，仍失败则停止并报告。

## 禁止事项

- 不要把小修复扩大成重构。
- 不要新增数据模型、隐私策略、诊断查询能力或跨端新功能。
- 不要生成 plan/task graph；需要多个 task 才能描述时停止并建议 `/ao-plan`。
- 不要绕过 workflow runner。
- 不要在目标项目不唯一时自行选择项目。
- 不要上传或写入原始日志、token、auth、prompt 或敏感输出。
- 不要自动切换工作流，除非用户明确要求。
