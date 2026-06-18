# ao-spec gate frontend template

读取 `frontend-template-selection.json` 和项目文件。检查模板存在、视图/组件/状态要求完整、模板不是简易单页退化，并检查前端实现契约可以传递到实现阶段。

必须写入 `$AO_ARTIFACTS_DIR/frontend-template-gate.json`。

如果 PRD 需要前端但没有模板或等价适配方案，结果必须为 FAIL。

如果 `frontend_required=true`，必须同时检查：

- `frontend_implementation.mode` 明确，且只能是 `independent_frontend`、`existing_frontend_adaptation` 或 `server_rendered_equivalent`。
- `frontend_implementation.stack_source` 可追溯，且来自项目已有栈、Spec 技术栈、项目标准、用户确认或产品契约。
- `independent_frontend` 和 `existing_frontend_adaptation` 必须有 `source_root`、`package_manifest`、`framework`、`language`、`package_manager`、`test_commands`、`build_commands` 和 `e2e_commands`。
- 从 0 创建且无已有前端时，不能选择 `server_rendered_equivalent`，除非有明确 `server_rendered_exception`。
- `server_rendered_equivalent` 必须证明已有 server-rendered 前端或明确产品约束，并声明同等质量标准、测试命令和 e2e 命令。
- gate 产物必须把最终选择摘要写入 `frontend-template-gate.json.implementation_contract`，供实现和 release review 回溯。

