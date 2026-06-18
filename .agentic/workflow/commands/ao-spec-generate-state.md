# ao-spec generate product state

读取 `imported-source.json`、导入后的 `source-prd.md`/`source-spec.md`、`project-inspection.json`。先基于真实项目上下文理解 PRD，再生成可执行产品状态。

必须写入：

- `$AO_ARTIFACTS_DIR/product-prd.md`
- `$AO_ARTIFACTS_DIR/product-contract.json`
- `$AO_ARTIFACTS_DIR/stories.json`
- `$AO_ARTIFACTS_DIR/progress.md`

`product-contract.json` 必须包含 product_goal、users、workflows、non_goals、domain_objects、states、frontend、backend、data、privacy、security 和 `acceptance_items`。每个验收项必须有稳定 id。

`stories.json` 必须以 story 驱动后续 loop，每个 story 包含 id、title、user_value、acceptance_ids、acceptance_criteria、technical_notes、depends_on、priority、risk、required_evidence、passes=false、status。

