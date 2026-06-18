# /ao-infra

处理项目控制面、workflow、command、skill、脚本入口或受管 infra 的修改，执行 `control-plane-change` 工作流。

## 用法

```text
/ao-infra <明确的控制面修改目标>
```

## 规则

- Skill：`.codex/skills/ao-infra/SKILL.md`
- 命令后的全部内容作为 `goal`。
- 读取本 command 文件后，继续读取 `.codex/skills/ao-infra/SKILL.md`。
- 再读取 `.agentic/workflow/control-plane-change.md` 和 `.agentic/workflow/definitions/control-plane-change.json`。
- 使用 `python scripts/ao.py workflow prepare --workflow control-plane-change --goal <目标>` 创建运行目录。
- 必须读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
- 只处理控制面文件，不混入业务应用代码。
- 必须在 run 目录写入 `infra-scope.md`、`implementation.md`、`changed-files.json` 和 `changed-files.txt`。
- `changed-files.json` 是机器对账 artifact；runner 会用 git 重新计算 implementation changed set，漏报、虚报或状态不一致必须失败。
- `changed-files.txt` 只用于人工摘要，不作为通过依据。
- 高风险控制面变更必须提供 sub agent 质疑式 review 的 `review/raw-findings.json` 和 `review/output.md`；runner 会生成 review receipt 和 gate result。
- 修改 managed infra 文件时必须同步 `agentic-infra/templates/project/` 和 `agentic.lock.json`。
- 完成前必须运行 `python scripts/ao.py agentic-check`。
- `complete --skip-verify` 不得跳过 changed-set、template/lock、review 或 artifact gate；高风险变更不得因此 `PASSED`。
- 最终使用 `python scripts/ao.py ao-infra complete --run-id <run_id> --goal <原目标> --summary-file <summary.txt> --changed-files-file <files.txt>` 写入 `run-report.md`。

## 示例

```text
/ao-infra 新增 Python 控制面入口并同步模板
```
