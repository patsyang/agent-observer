# /ao-small

处理小修复、小配置、小 UI 调整或低风险 bug，执行 `small-change` E2E 工作流。它的核心是小修准入门禁，不是短计划。

## 用法

```text
/ao-small <明确的小目标>
/ao-small --project <项目名> <明确的小目标>
/ao-small --scope <scope> <明确的小目标>
```

## 规则

- Skill：`.codex/skills/ao-small/SKILL.md`
- 命令后的全部内容作为 `goal`；提供 `--project` 时传入已注册业务项目。
- 用户可以只输入一句局部问题，workflow 必须生成 `repro.md`、`small-scope.json` 和 `verification.json`。
- `/ao-small` 不生成 `plan.md`、`tasks.json` 或 `task-graph.json`。
- `--project-root <path>` 仅用于一次性未注册目标仓库；长期项目必须先注册再使用 `--project`。
- 业务项目运行前必须存在 confirmed `.agentic/stack-contract.json`；缺失时 prepare 阶段失败，先使用 `/ao-project -r <项目> <项目根目录>` 完成一步式项目接入并确认技术栈 profile。
- `scope` 支持 `agentic-infra`、`control-plane`、`repo`，以及目标业务仓库内显式相对边界。
- 未提供 `project`、`project_root` 或 `scope` 时，workflow 必须解析唯一 `project_scope`；多个候选直接失败。
- 读取本 command 文件后，继续读取 `.codex/skills/ao-small/SKILL.md`。
- 再读取 `.agentic/workflow/small-change.md` 和 `.agentic/workflow/definitions/small-change.json`。
- 使用 `python scripts/ao.py small-change run --project <项目名> --goal <目标>` 启动业务项目完整运行。
- 必须读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
- workflow 必须创建隔离 worktree、完成 small-scope gate、repro/signal、最小实现、定向验证、独立审查、小修验收 gate 和报告。
- 最终 `review` 节点必须产出 `acceptance-matrix.json`、`component-evidence.json`、`command-coverage.json`，并带相同 `stack_contract_ref`。
- 先做 small-scope gate；涉及数据模型、隐私策略、跨端新功能、多组件修改或大重构时失败，建议改用 `/ao-plan` 或 `/ao-spec`。
- Bug 修复必须先补回归测试。
- 完成后运行受影响测试；同一失败最多修复 3 次，仍失败则停止并报告。
- `run-report.md` 由 workflow run 写入；失败时输出 run_id、失败节点和 resume 命令。

## 示例

```text
/ao-small 修复首页状态文案显示不完整
/ao-small --project app-a 修复 Dashboard 未读消息数量显示不更新
```
