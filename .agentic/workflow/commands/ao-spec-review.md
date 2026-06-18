# ao-spec independent review

只读审查。读取 PRD、product contract、production spec、stories、tasks、implementation-state、full-verify、git diff 和所有证据。

必须写入：

- `$AO_ARTIFACTS_DIR/review.md`
- `$AO_ARTIFACTS_DIR/review-findings.json`

对每个已通过 story 给出 OK、WARN 或 FAIL。FAIL 必须包含 acceptance_id、证据路径、阻断原因和 required_fix。

