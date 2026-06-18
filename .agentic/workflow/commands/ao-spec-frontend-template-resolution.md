# ao-spec frontend template resolution

读取 `product-contract.json`、`production-spec.md`、`project-inspection.json`。判断是否需要前端模板，选择 dashboard 或 observability-dashboard 模板，或输出既有前端适配方案。

本节点也是技术栈定基节点：技术栈不得在 implement 阶段临时猜测。必须从以下来源之一选择并写明来源：

- `project_existing`：目标项目已有前端栈和入口。
- `spec_tech_stack`：PRD/Spec/production-spec 明确指定。
- `project_standard`：项目规则或 AGENTS/README 明确约束。
- `user_confirmed`：用户在输入或规格中明确确认。
- `product_contract`：产品契约明确要求特定运行形态。

必须写入：

- `$AO_ARTIFACTS_DIR/frontend-template-selection.json`
- `$AO_ARTIFACTS_DIR/frontend-template-rationale.md`

需要前端时，selection 必须包含 template_id、required_views、required_components、required_states、required_interactions、api_contracts、e2e_scenarios、visual_quality_rubric。

需要前端时还必须包含 `frontend_implementation`：

```json
{
  "mode": "independent_frontend | existing_frontend_adaptation | server_rendered_equivalent",
  "stack_source": "project_existing | spec_tech_stack | project_standard | user_confirmed | product_contract",
  "source_root": "frontend",
  "package_manifest": "frontend/package.json",
  "framework": "React",
  "language": "TypeScript",
  "package_manager": "npm",
  "test_commands": ["npm --prefix frontend test"],
  "build_commands": ["npm --prefix frontend run build"],
  "e2e_commands": ["npx playwright test"]
}
```

从 0 创建且 `project-inspection.json.frontend.exists=false` 时，默认必须选择 `independent_frontend`。不得因为后端语言是 Go/Python/Java 就把前端降级成后端模板或 HTML form。

只有在目标项目已有 server-rendered 前端，或 PRD/Spec 明确要求 single-binary/server-rendered 交付时，才允许 `server_rendered_equivalent`。此时必须额外写入：

```json
{
  "server_rendered_exception": {
    "constraint_source": "production_spec | product_contract | user_confirmed",
    "explicit_product_constraint": true,
    "rationale": "为什么不能或不应建立独立前端工程"
  },
  "frontend_implementation": {
    "mode": "server_rendered_equivalent",
    "source_root": "internal/server/http",
    "test_commands": ["..."],
    "e2e_commands": ["..."],
    "quality_equivalence": "说明如何达到独立前端同等交互、状态、响应式和可访问性标准"
  }
}
```

该选择会被后续门禁和 implement-story-loop 使用；不能只写在 rationale 中。

