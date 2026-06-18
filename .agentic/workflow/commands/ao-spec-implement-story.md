# ao-spec implement story

每轮只实现一个 story。读取 `stories.json`、`tasks.json`、`production-spec.md`、`project-inspection.json`、`frontend-template-selection.json`、`frontend-template-gate.json`、`progress.md` 和目标项目规则。

选择 `passes != true`、依赖已通过、priority 最小的 story。若全部完成，只输出 `<promise>COMPLETE</promise>`。

实现当前 story 时必须写或更新测试，运行对应验证，更新 `stories.json`、`implementation-state.json` 和 `progress.md`。未验证不得把 story 标为通过。不得实现多个 story。

如果当前 story、task 或验收项涉及 UI、Dashboard、browser、form、viewport、frontend_contracts 或 frontend acceptance：

- 必须遵守 `frontend-template-selection.json.frontend_implementation`，不能临时改用未声明技术栈。
- `mode=independent_frontend` 时必须在声明的 `source_root` 下实现前端源码，并接入声明的 test/build/e2e 命令；不得只在后端 handler 中拼 HTML 或只写 API 测试。
- `mode=existing_frontend_adaptation` 时必须复用既有前端入口、路由、组件和测试约定。
- `mode=server_rendered_equivalent` 时只能在 gate 已批准的约束内实现，并必须补同等交互、状态、响应式和可访问性证据。
- 完成状态必须在 per-story verification 中记录实际执行的前端 test/build/e2e 命令和证据路径。
