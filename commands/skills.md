# /skills

列出当前项目支持的 Agentic Coding 斜杠命令。

## 用法

```text
/skills
```

## 规则

- 第一动作扫描 `.codex/skills/*/SKILL.md`。
- 同时扫描 `commands/*.md`，建立 command 映射。
- 输出当前项目支持的命令、对应 workflow、用途和入口文件。
- 只输出当前 `commands/` 中存在的入口。

## 当前命令

| Command | Skill | Workflow | 用途 |
| --- | --- | --- | --- |
| `/ao-spec` | `ao-spec` | `spec-driven` | 从 PRD、规格或大功能开始开发 |
| `/ao-plan` | `ao-plan` | `plan-execute` | 执行一个普通功能切片 |
| `/ao-small` | `ao-small` | `small-change` | 小修复、小配置、小 UI 调整 |
| `/ao-infra` | `ao-infra` | `control-plane-change` | 控制面、workflow、command、skill 或受管 infra 修改 |
| `/ao-project` | 无 | 无 | 管理业务项目注册表 |
| `/skills` | 无 | 无 | 列出项目命令 |
