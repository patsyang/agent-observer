# ao-spec production spec

读取 `product-contract.json`、`stories.json` 和 `project-inspection.json`，生成工程可实现规格。

必须写入：

- `$AO_ARTIFACTS_DIR/production-spec.md`
- `$AO_ARTIFACTS_DIR/api-contract.json`
- `$AO_ARTIFACTS_DIR/data-contract.json`

`production-spec.md` 必须使用以下精确二级章节标题，不能改名、合并或只用近义标题：

1. `Product Outcome`
2. `User Roles and Production Workflows`
3. `Domain Objects and States`
4. `Frontend Product Surface`
5. `Backend and Data Contracts`
6. `Error, Empty, Partial and Recovery States`
7. `Security and Privacy Boundaries`
8. `Operational Concerns`
9. `Release Gates`
10. `Acceptance Matrix Draft`

如果需要补充 Client Commands、Local State、Packaging、Verification Strategy 或 Acceptance Trace，必须放入以上章节内，或作为三级章节出现；不得替代这些精确二级章节。

`Frontend Product Surface` 章节必须明确技术栈决策时点：

- 已有前端：写明现有 framework、source root、package manifest、test/build/e2e 命令来源。
- 新建前端：写明期望独立前端工程或明确的产品约束；不得只写“可后端渲染或 SPA 均可”这类不可执行选择。
- 若确需 server-rendered/single-binary，必须写明产品约束和等价质量要求，供 `frontend-template-resolution` 生成 `server_rendered_exception`。
- 所有前端验收必须能追溯到具体用户动作、UI 状态、API/持久化断言和自动化命令。
