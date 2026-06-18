# ao-spec gate production spec

读取 `production-spec.md`、`api-contract.json`、`data-contract.json`、`product-contract.json`。

必须写入：

- `$AO_ARTIFACTS_DIR/spec-gate.json`
- `$AO_ARTIFACTS_DIR/spec-gate.md`

检查 required sections、API/data/frontend/client/package coverage、acceptance trace、隐私禁止项和 unresolved open questions。任一必需项缺失时结果为 FAIL。

required sections 必须按以下精确二级章节标题检查：

- `Product Outcome`
- `User Roles and Production Workflows`
- `Domain Objects and States`
- `Frontend Product Surface`
- `Backend and Data Contracts`
- `Error, Empty, Partial and Recovery States`
- `Security and Privacy Boundaries`
- `Operational Concerns`
- `Release Gates`
- `Acceptance Matrix Draft`

`spec-gate.json` 必须包含顶层 `"result": "PASS"` 或 `"result": "FAIL"`。任一检查失败时必须写 `"result": "FAIL"`，并列出 `failures`；runner 会把非 PASS 结果视为节点失败。
