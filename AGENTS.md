# AGENTS.md

## 执行原则

- 编码前先确认目标、边界和成功标准；存在多种合理解释时停止并说明分歧，不自行选择。
- 测试脚本的防回归不能当作“事故纪念碑”。
- 能用更小改动解决时，优先采用更小方案；不添加需求之外的功能、配置、抽象或通用框架。
- 修改必须精准关联当前请求、规格或失败测试；不顺手重构、格式化、删除无关代码或清理历史遗留问题。
- 每个非平凡任务都要转成可验证目标：缺陷先复现，功能先定义可观察行为，完成前运行对应验证。
- 简单一行修复、纯文档或明确配置调整可轻量执行，但仍要保持最小改动和必要验证。

## 工作入口

- 斜杠命令以 `commands/<command>.md` 为唯一入口；不要从 `AGENTS.md` 推断 skill、workflow 或输入格式。
- 斜杠命令第一动作：读取 `commands/<command>.md`。
- command 文件是 skill、workflow、输入解析和执行入口的唯一映射源。
- 按 command 文件读取对应 skill、workflow 契约，并创建运行目录。
- 命令输入不完整时停止，说明缺少的参数。
- 当前仓库只提交控制面与受管 infra；`apps/` 仅可作为本地业务工作区挂载点，不纳入 git、模板或 `verify`。
- infra 规格位于 `agentic-infra/specs/<feature>/`。
- 新业务功能、高风险变更或长期能力没有产品事实时走 `/ao-spec` 生成 product contract、stories、production spec 和 task graph；普通 goal 走 `/ao-plan` 生成 slice brief、plan 和 task graph；明确小修走 `/ao-small`，不直接扩展成大段实现。
- 每次只做一个最小垂直切片；只同步本切片实际触达的后端、前端、collector 和测试，不为“闭环”扩大范围。
- 服务端不得依赖 Codex 私有表结构；只能依赖本项目定义的结构化 telemetry 数据和数据访问层。

## 任务分流

- 应用功能、业务缺陷和用户可见行为修改走 `/ao-spec`、`/ao-plan`、`/ao-small`。
- `AGENTS.md`、`commands/`、`.codex/skills/`、`.agentic/workflow/`、`scripts/`、`tools/workflow_runner/`、`agentic-infra/templates/project/`、`agentic.lock.json` 的修改走 `/ao-infra`。
- 控制面修改不默认要求 pytest、Vitest 或 Playwright；必须验证命令入口、workflow 契约、模板同步、lock 同步和 `python scripts/ao.py agentic-check`。
- 控制面修改不得顺手改业务应用代码；发现业务问题只记录，不混入同一切片。

## 工作流治理

- 新工作流必须先补契约文档，说明输入参数、产物、日志、验证和退出条件。
- 新工作流必须同时补 `.agentic/workflow/definitions/<workflow>.json`。
- 通过项目 workflow 执行的每次运行都要写报告到 `ai_docs/runs/`，报告包含参数、产物、验证和风险。
- 工作流运行报告必须包含本次目标、边界、成功标准、实际修改范围、验证命令、结果和未覆盖风险。
- 日志事件字段以 `.agentic/workflow/workflow-governance.md` 为准，至少包含 `run_id`、`workflow`、`step`、`status`、`message`、`artifact_path`。
- Codex、Trae、Claude 等基础设施只能作为 runtime adapter 接入，不允许复制或改写工作流规则。
- 需要调用 Agent runtime 的非交互执行走 `python scripts/ao.py codex-adapter`；prepare、complete、check、init、update 使用 `python scripts/ao.py ...` 标准入口，不得绕过标准运行目录和事件报告。
- 修改 managed infra 文件时必须同步 `agentic-infra/templates/project/`，并让 `python scripts/ao.py agentic-check` 通过。

## Shell 纪律

- 持久入口只用 `python scripts/ao.py ...`。
- 不新增、调用或扩展项目自有 `.ps1`；不在 README、package、workflow、模板中写 PowerShell 入口。
- 临时诊断可用 PowerShell；诊断命令不得固化。

## TDD 与验证

- 开始实现前写明本次切片的成功标准；交付时逐项说明已通过、未运行和剩余风险。
- 后端行为变更先写 pytest，再实现。
- 前端用户可见行为、组件状态或数据流变更先写 Vitest，再实现。
- 跨端用户流程变更必须写或更新 Playwright e2e。
- Bug 修复必须补一个先失败、后通过的回归测试。
- 测试脚本只负责编排固定验证入口，不因单次改动新增脚本；新增测试内容必须绑定新增/变更的可观察行为或回归缺陷，并优先复用现有 fixture 与入口。
- 每次交付前至少运行受影响测试；无法运行要说明原因。

## 文件规模

- React 组件文件目标不超过 180 行，硬上限 250 行。
- TS/TSX 模块目标不超过 220 行，硬上限 300 行。
- Python 业务代码文件不超过 500 行。
- Python 单个函数或类不超过 100 行。
- 测试文件可以稍长，但超过 350 行要拆分。
- 文件接近上限时先拆模块，不要继续追加条件分支。

## 代码组织
- 不新建相似组件、Hook、工具函数或脚本；先查已有实现再写。
- 同一 UI 结构、状态逻辑或数据转换第二次出现时，提取组件、Hook 或纯函数。
- 展示组件只接收 props，不写 API 调用、解析逻辑或业务规则。
- 业务应用代码不得提交到当前仓库；如需本地调试，可放在被忽略的 `apps/<app>/` 工作区。
- 不得在仓库根目录新增后端、前端、collector 或 e2e 业务源码目录。
- 后端不新建相似 use case、repository、adapter、schema 或工具函数；先查同业务模块已有实现。
- 同一业务规则、查询/持久化流程、外部系统调用或数据转换第二次出现时，提取用例、repository/adapter 方法或纯函数。
- 后端只在业务能力或外部依赖边界上抽象；router 保持 HTTP 薄层，业务规则进模块用例，数据库和外部系统经 repository 或 adapter 注入，未出现第二个真实调用点前不抽通用基类或泛型服务。
- 后端按业务能力拆分模块；新增能力时建立清晰模块边界，不塞入 router 或 `app.py`。
- collector 只负责本机探测、脱敏、游标、outbox 和上报，不放服务端聚合逻辑。

## 隐私边界

- 禁止上传原始日志、原始命令输出、prompt、token、auth 文件内容。
- 诊断查询只允许白名单模板；禁止服务端下发任意 SQL、shell、grep、文件读取。
- 身份、账号、设备标识只允许本地哈希后上报。
- 诊断查询只能上传结构化结论、计数、类别、时间范围和脱敏摘要。
- 测试只能使用合成或最小化 fixture，不读取真实用户 `.codex` 数据。

## 长任务纪律

- 长任务先写短计划，再按任务清单推进。
- 运行服务、测试、e2e 时要等待结果，不留下悬挂进程。
- 超过 60 秒的命令要记录命令、进度、PID/URL/日志路径。
- 发现失败先建立可重复信号，再修复；不要靠猜测改代码。
- 不回滚用户已有改动，除非用户明确要求。
