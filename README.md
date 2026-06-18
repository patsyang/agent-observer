# agent-observer

本项目已接入 Agentic Coding 工作流基础设施。

## 工作流入口

```text
python scripts/ao.py workflow list
```

Codex 中可使用：

```text
/ao-spec agent_observer -prd D:\workspace\prd\agent_observer.md
/ao-plan 实现一个普通功能切片
/ao-small 修复一个明确的小问题
/ao-infra 修改项目控制面入口或 workflow 契约
```

## 目录说明

```text
commands/       项目斜杠命令入口
.codex/skills/  Codex skill 执行规则
.agentic/workflow/  工作流契约、定义、模板和 schema
apps/           本地业务工作区挂载点，默认忽略，不提交
ai_docs/        本地输入、计划和运行报告，不提交
scripts/        项目开发与工作流脚本
tools/          工作流控制平面
```

## 业务项目注册

`apps/` 只作为本机业务工作区挂载点。业务应用代码应在自己的 Git 仓库中提交；
当前项目只通过注册表定位目标仓库：

```text
python scripts/ao.py project register --name app-a --root D:\workspace\apps\app-a
python scripts/ao.py project list
python scripts/ao.py project status app-a
```

业务 workflow 使用注册名运行，运行产物写入目标项目 `.agentic/project.json`
中的 `runtime.runs_dir`，隔离 worktree 写入 `runtime.worktrees_dir`，不会写入当前控制仓库：

```text
python scripts/ao.py plan-execute run `
  --project app-a `
  --goal "实现业务功能"
```

## 验证

`python scripts/ao.py lint`、`python scripts/ao.py test`、`python scripts/ao.py e2e`
和 `python scripts/ao.py verify` 只验证当前项目控制面。业务代码验证应在业务仓库或本地业务工作区自己的入口中执行。
