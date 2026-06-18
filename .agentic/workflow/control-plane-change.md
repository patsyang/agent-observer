# control-plane-change 工作流契约

## 适用场景

- 修改 `AGENTS.md`、`commands/`、`.codex/skills/` 或 `.agentic/workflow/`。
- 修改 workflow runner、脚本入口、adapter 或验证门禁。
- 修改 `agentic-infra/templates/project/`、`agentic-infra/manifest.json` 或 `agentic.lock.json`。
- 需要同步受管 infra 模板和安装副本的项目治理调整。

## 输入参数

必需二选一：

- `goal`
- `goal_path`

禁止同时提供 `goal` 和 `goal_path`。

## 运行阶段

```text
scope-check -> read-contracts -> minimum-contract-diff -> sync-template -> update-lock -> finalizer-review -> finalizer-verification -> report
```

## 必须产物

- `infra-scope.md`。
- `implementation.md`。
- `changed-files.json`，机器可校验的 implementation changed set 声明。
- `changed-files.txt`，人工可读变更摘要。
- 控制面文件、模板或 lock 的最小修改。
- 高风险控制面变更的 `review/raw-findings.json` 和 `review/output.md`。
- runner 生成的 `gate-results/*.json` 和 `infra-acceptance.json`。
- `ai_docs/runs/<run_id>/run-report.md`。

## 控制面边界

允许：

- 命令、skill、workflow 契约调整。
- 脚本入口、workflow runner、adapter 和验证门禁调整。
- 受管 infra 模板、manifest 和 lock 同步。
- README、AGENTS 或 spec template 中与控制面入口直接相关的说明。

禁止：

- 业务应用功能开发。
- 后端、前端、collector 的业务行为修改。
- 为了顺手修问题而改动无关模块。
- 未同步模板或 lock 的受管 infra 修改。

如果命中禁止项，停止并建议用户改用 `plan-execute` 或 `spec-driven`。

## 执行纪律

- 先确认受影响文件是否属于 `agentic-infra/manifest.json` 管理范围。
- `changed-files.json` 是必需 artifact；runner 会用 git 重新计算 implementation changed set 并精确对账。
- `changed-files.txt` 只用于人工摘要，不参与风险分级或通过判定。
- 受管文件必须同时更新根安装副本和 `agentic-infra/templates/project/`。
- 修改受管文件后必须更新 `agentic.lock.json` 对应 hash。
- 持久入口统一使用 `python scripts/ao.py ...`；不得新增、调用或扩展项目自有 `.ps1`。
- 高风险控制面变更必须提供 sub agent 质疑式 review 的结构化 raw findings；runner 只信任 `review/raw-findings.json`，不信任聊天结论。
- 不做计划外重构，不混入业务应用代码。

## 验证门禁

- 必须运行 `python scripts/ao.py agentic-check`。
- 修改 `scripts/ao.py` 或 `tools/workflow_runner/` 时必须运行 `uv run --project tools/workflow_runner python -m pytest tools/workflow_runner/tests`。
- 修改 `scripts/ao.py` 或 workflow runner 时至少运行一个 Python 入口 smoke。
- `complete` 会写入 `gate-results/changed-set.json`、`gate-results/risk-profile.json`、`gate-results/template-lock-gate.json`、`gate-results/review-gate.json`、`gate-results/verification.json` 和 `infra-acceptance.json`。
- `--skip-verify` 不能跳过 changed-set、template/lock、review 或 artifact gate；高风险变更使用 `--skip-verify` 不得标记为 `PASSED`。
- 验证结论只能是 `PASSED`、`NEEDS_COMPLETE`、`NEEDS_VERIFICATION` 或 `FAILED`；不能把未执行说成通过。

## Resume 语义

`workflow resume` 对 `control-plane-change` 不得直接复用节点状态标记通过。resume 成功后必须重新进入同一 completion finalizer；finalizer 未通过时 run status 只能是 `NEEDS_COMPLETE`、`NEEDS_VERIFICATION` 或 `FAILED`。

## 失败处理

如果 `agentic-check` 失败，先判断是模板未同步、lock 未更新还是本地项目修改冲突；只修复对应控制面问题，不扩大到业务代码。
