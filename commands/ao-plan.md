# /ao-plan

执行普通功能切片，使用 `plan-execute` E2E 工作流从 goal 生成标准 slice brief、plan、task graph，再自动开发、审查、修复、验证、验收和报告。

## 用法

```text
/ao-plan <目标|goal_path|spec_path|plan_path>
/ao-plan --project <项目名> <目标>
/ao-plan --scope <scope> <目标>
```

## 规则

- Skill：`.codex/skills/ao-plan/SKILL.md`
- 命令后的全部内容可以是自然语言 goal、goal 文件、spec 文件或标准 plan 文件；提供 `--project` 时传入已注册业务项目。
- 用户不需要会写 plan。未提供标准 `plan_path` 时，workflow 必须先生成 `slice-brief.md`、`plan.md`、`tasks.json` 和 `task-graph.json`。
- `plan_path` 是高级入口，不是免检通道；必须通过 plan contract gate 和 task graph gate。
- `--project-root <path>` 仅用于一次性未注册目标仓库；长期项目必须先注册再使用 `--project`。
- 业务项目运行前必须存在 confirmed `.agentic/stack-contract.json`；缺失时 prepare 阶段失败，先使用 `/ao-project -r <项目> <项目根目录>` 完成一步式项目接入并确认技术栈 profile。
- `scope` 支持 `agentic-infra`、`control-plane`、`repo`，以及目标业务仓库内显式相对边界。
- 未提供 `project`、`project_root` 或 `scope` 时，workflow 必须解析唯一 `project_scope`；多个候选直接失败。
- 读取本 command 文件后，继续读取 `.codex/skills/ao-plan/SKILL.md`。
- 再读取 `.agentic/workflow/plan-execute.md` 和 `.agentic/workflow/definitions/plan-execute.json`。
- 使用 `python scripts/ao.py plan-execute run ...` 启动完整运行。
- 必须读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
- 如果没有 `plan_path`，workflow 先生成 `slice-brief.md`、标准 `plan.md`、`tasks.json` 和 `task-graph.json`。
- `plan.md`、`tasks.json` 和 `task-graph.json` 必须引用项目级 `stack_contract_ref`，并把 task 映射到契约组件、源码根、验收项、验证命令和 done signal。
- 进入实现前必须通过 `plan-contract-gate` 和 `task-graph-gate`。
- gate 失败时只允许修正 slice brief、计划或任务图，不允许继续写实现代码。
- `/ao-plan` 不生成产品级 `product-contract.json`、`stories.json` 或长期 acceptance matrix；如果 goal 需要改变产品事实，必须失败并建议升级 `/ao-spec`。
- 先补受影响测试，再实现代码。
- 多任务通过 task graph 和并行 worker 执行，每个 worker 只能修改自己的 `write_set`。
- 默认运行项目验证入口。
- 最终 `fix-loop` 必须产出 `acceptance-matrix.json`、`component-evidence.json`、`command-coverage.json`，并带相同 `stack_contract_ref`。
- `run-report.md` 由 workflow run 写入；失败时输出 run_id、失败节点和 resume 命令。

## 示例

```text
/ao-plan 实现客户端 outbox 上传，断网时本地排队，恢复后继续上传
/ao-plan --project app-a 实现客户端 outbox 上传，断网时本地排队，恢复后继续上传
```
