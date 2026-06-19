---
name: ao-infra
description: 修改当前项目控制面、workflow、command、skill、脚本入口或受管 infra 时使用。对应 control-plane-change 工作流。
---

# ao-infra

本 Skill 服务 `/ao-infra` 命令，执行 `control-plane-change` 工作流。

## 触发场景

- 修改 `AGENTS.md`。
- 修改 `commands/`、`.codex/skills/`、`.agentic/workflow/`。
- 修改 `scripts/ao.py`、workflow runner、adapter 或验证门禁。
- 修改 `agentic-infra/templates/project/`、`agentic-infra/manifest.json` 或 `agentic.lock.json`。

## 输入

命令后的内容应是明确的控制面修改目标，例如：

```text
/ao-infra 新增 Python 控制面入口并同步模板
```

如果目标不明确，先问一个关键问题，不要扩大范围。

## 执行规则

1. 全程使用中文输出。
2. 读取 `AGENTS.md`。
3. 读取 `commands/ao-infra.md`。
4. 读取 `.agentic/workflow/workflow-governance.md`。
5. 读取 `.agentic/workflow/control-plane-change.md`。
6. 读取 `.agentic/workflow/definitions/control-plane-change.json`。
7. 使用 `python scripts/ao.py workflow prepare --workflow control-plane-change --goal <目标>` 准备运行。
8. 读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
9. 先做控制面边界判断；涉及业务应用功能时停止并建议改用 `/ao-plan` 或 `/ao-spec`。
10. 在 run 目录写入 `infra-scope.md`，明确目标、边界、成功标准和预计触达路径。
11. 只做最小契约修改，保持根文件、模板和 lock 同步。
12. 在 run 目录写入 `implementation.md`、`changed-files.json` 和 `changed-files.txt`；`changed-files.json` 必须包含 path、status、old_path，并会被 runner 与 git implementation changed set 对账。
13. 高风险控制面变更必须启动 sub agent 质疑式 review，并把结构化 findings 写入 `review/raw-findings.json`，把可读输出写入 `review/output.md`。
14. 有 P0/P1 或未处置 P2 时必须继续修复并再次 review，直到 review gate 可通过。
15. 持久入口统一使用 Python；不得新增、调用或扩展项目自有 `.ps1`。
16. 完成前运行 `python scripts/ao.py agentic-check`。
17. 涉及 `tools/workflow_runner/` 或 `scripts/ao.py` 时运行 `uv run --project tools/workflow_runner python -m pytest tools/workflow_runner/tests`。
18. 使用 `python scripts/ao.py ao-infra complete --run-id <run_id> --goal <原目标> --summary-file <summary.txt> --changed-files-file <files.txt>` 写入 `run-report.md`；complete 会重新运行 control-plane finalizer，不信任手写 PASS。

## 禁止事项

- 不要混入业务应用代码修改。
- 不要绕过 workflow runner 自建运行目录。
- 不要只改根文件不改模板，或只改模板不更新 lock。
- 不要手写 `infra-acceptance.json` 或 `gate-results/*.json` 伪造通过。
- 不要把 `changed-files.txt` 当作门禁事实；门禁事实来自 git 和 `changed-files.json` 对账。
- 不要新增项目自有 `.ps1` 持久入口。
