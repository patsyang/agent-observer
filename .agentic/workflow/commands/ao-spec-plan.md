# ao-spec implementation plan

读取 `production-spec.md`、`stories.json`、`project-inspection.json`。只做规划，不写实现代码。

必须写入：

- `$AO_ARTIFACTS_DIR/plan.md`
- `$AO_ARTIFACTS_DIR/tasks.md`
- `$AO_ARTIFACTS_DIR/tasks.json`
- `$AO_ARTIFACTS_DIR/task-graph.json`

每个 task 必须绑定 story、acceptance、observable_outcome、files_expected、tests_required、verification_commands、done_signal、dependencies、risk、size。禁止 L/XL task，禁止不可验收标题。

如果产品需要前端：

- 计划必须保留前端实现任务，不能只写 Dashboard API。
- task 必须引用 `frontend-template-selection.json.frontend_implementation` 中的 `mode`、`source_root`、测试命令和 e2e 命令。
- `independent_frontend` 必须至少拆出 API contract/adapter、前端源码、前端测试/e2e 三类可验证工作；可以垂直切片，但不能把 UI 降级到后端 HTML form。
- Dashboard/API 与 Dashboard/UI 可以同属一个用户 workflow，但 task 层必须分别列出 API 文件、前端文件和验证命令。
- 若选择 `server_rendered_equivalent`，计划必须写明批准来源、质量等价验证和剩余风险。

