# /ao-project

管理业务项目注册表，使用短参数映射到 `python scripts/ao.py project ...`。

## 用法

```text
/ao-project -r <项目名> <项目根目录> [--model <model_id>] [--stack-profile <profile_id>]
/ao-project -l
/ao-project -s <项目名或ID>
/ao-project -b <项目名或ID> <新项目根目录>
/ao-project models
/ao-project stack profiles
/ao-project stack status <项目名或ID>
/ao-project stack confirm <项目名或ID> --from <stack-contract.json>
```

## 参数

| 参数 | 含义 | 映射入口 |
| --- | --- | --- |
| `-r` | 接入并注册业务项目 | `python scripts/ao.py project register --name <项目名> --root <项目根目录> [--model <model_id>] [--stack-profile <profile_id>]` |
| `-l` | 列出已注册业务项目 | `python scripts/ao.py project list` |
| `-s` | 查看业务项目状态 | `python scripts/ao.py project status <项目名或ID>` |
| `-b` | 重新绑定业务项目根目录 | `python scripts/ao.py project rebind <项目名或ID> --root <新项目根目录>` |
| `models` | 列出可选 runtime 模型 | `python scripts/ao.py project models` |
| `stack profiles` | 列出可选技术栈 profile | `python scripts/ao.py project stack profiles` |
| `stack status` | 查看项目级技术栈契约状态 | `python scripts/ao.py project stack status <项目名或ID>` |
| `stack confirm` | 高级入口：从自定义 JSON 确认并写入项目级技术栈契约 | `python scripts/ao.py project stack confirm <项目名或ID> --from <stack-contract.json>` |

## 规则

- 本命令无 Skill、无 workflow；只封装项目注册表入口。
- 四个短参数互斥，一次只能使用一个；`models` 和 `stack` 子命令不与短参数混用。
- 命令输入不完整时停止，并说明缺少的参数。
- `<项目根目录>` 和 `<新项目根目录>` 可使用绝对路径或相对当前仓库的路径。
- `-r` 是项目接入入口：会按项目状态注册、初始化或配置 runtime，并在输出中分层报告 registration、runtime 和 readiness。
- 目标项目缺少有效 runtime 模型且未传 `--model` 时，底层命令返回 `NEEDS_MODEL_SELECTION`；命令处理方必须把本次注册保持为待选择状态，列出可选模型并等待用户直接回复模型 id 或 label。
- 用户下一条消息如果只包含一个候选模型 id 或 label，命令处理方必须沿用原始 `-r <项目名> <项目根目录>` 参数自动追加 `--model <model_id>` 续跑注册，不要求用户重输完整命令。
- 用户回复不匹配候选模型时，停止并说明可选模型；不得猜测、不得静默使用默认模型。
- 目标项目已有有效 `.agentic/project.json` 和 `model.id` 时，`-r` 未传 `--model` 会沿用已有模型；传入 `--model` 才更新 runtime 配置。
- 目标项目缺少有效 `.agentic/stack-contract.json` 时，注册会自动使用默认技术栈 profile 生成 confirmed stack contract；不得要求用户手工准备 JSON 或另行执行 `stack confirm`。
- 默认技术栈 profile 是 `default-web-app`：前端 React + TypeScript + Vite + npm，后端 Python + FastAPI + pytest + uv/pip，客户端无独立客户端，数据库 SQLite。
- 用户需要自定义技术栈时，可在注册时传 `--stack-profile <profile_id>`；更复杂迁移场景才使用高级 `stack confirm --from <json>`。
- 注册完成的成功状态应为 `REGISTERED_READY`；此时项目必须同时具备 registry、runtime model 和 confirmed stack contract，可直接运行 `/ao-small`、`/ao-plan`、`/ao-spec`。
- `models` 只展示可由用户选择的模型；内部隐藏模型不得出现在列表中。
- `stack profiles` 只展示用户可选技术栈 profile；默认项必须标识清楚。
- 输出直接采用底层 `python scripts/ao.py project ...` 的 JSON 或错误信息，不额外包装。
- `stack confirm` 只作为高级/迁移入口，普通注册流程不得要求用户手工准备 stack contract JSON。
- `/ao-small`、`/ao-plan`、`/ao-spec` 对业务项目运行前必须能读取 confirmed stack contract；普通项目应通过 `/ao-project -r` 一步式接入生成。

## 示例

```text
/ao-project models
/ao-project stack profiles
/ao-project -r app-a D:\workspace\apps\app-a --model codex-gpt-5 --stack-profile default-web-app
/ao-project -l
/ao-project -s app-a
/ao-project -b app-a D:\workspace\projects\app-a
/ao-project stack status app-a
/ao-project stack confirm app-a --from D:\workspace\projects\app-a\stack-contract.draft.json
```
