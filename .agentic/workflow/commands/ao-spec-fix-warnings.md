# ao-spec fix warnings

你是 spec-driven 工作流的 fix agent。review 阶段已产出 `review.md`、`review-findings.json`、`review-gate.json`。你的任务：**只处理 actionable `FAIL` 与 `WARN`**，处理不了的标 BLOCKED，不得掩盖、删除或降级 finding。

## 黄金规则

- 不改 `stories.json` 的 `passes` 状态（passes 是 implement 的事实来源）。
- 不掩盖、删除或降级 finding；finding 只能通过实际修复关闭。
- 最小修复，不扩大需求，不顺手重构。
- 修复失败不伪装为通过，标 BLOCKED 即可。
- 前端 finding 必须补真实 UI 行为验证；隐私/打包/服务端/客户端 finding 必须补对应行为证据。

## Phase 0：加载状态

读取 review 产物和项目规则：

```bash
cat "$AO_ARTIFACTS_DIR/review-findings.json"
cat "$AO_ARTIFACTS_DIR/review.md"
cat "$AO_ARTIFACTS_DIR/review-gate.json"
cat AGENTS.md 2>/dev/null
```

收集本次实现的 git 变更范围（只看本次 spec run 引入的改动，避免读全量源码）：

```bash
base="${AO_BASE_COMMIT:-$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)}"
git log --oneline --no-merges "$base..HEAD"
git diff --stat "$base..HEAD"
git diff "$base..HEAD"
```

优先使用运行环境中的 `AO_BASE_COMMIT`（若已注入），避免把历史分支上的旧提交纳入修复范围。**不要**为了"了解全局"而读取整个模块树或全量 spec——按 review 引用的 `file:line` 定向读取即可。

## Phase 1：解析待修复清单

从 `review-findings.json` 中提取所有 `actionable` 的 `FAIL` 与 `WARN`：

- 逐项列出 finding id、severity、指向文件、问题描述
- 按文件/模块聚类，便于定向修复

**不处理**：

- 非 actionable 的 finding（如 informational / info 级别）
- 已在 `review-gate.json` 中标记为 accepted 的 finding

如果没有 actionable finding，直接进入 Phase 5，写 `fix-state.json.status = NO_ACTIONABLE_WARNINGS`。

## Phase 2：BLOCKED 判定

下列情形不强求自动修复，直接标 BLOCKED 并继续：

- 需要产品判断、架构取舍或扩大需求范围
- 需要跨多个 story 大规模重构
- 修复风险过高（关键路径、数据迁移、外部服务）
- 需求不清或存在矛盾
- 环境/依赖级失败（测试收集/加载阶段崩溃，非本次代码引入）

BLOCKED 的 finding 不算 actionable，不会触发 loop 重试。

## Phase 3：修复

逐项处理可修复的 actionable finding：

1. 阅读 review 引用的 `file:line` 与周边相似实现（定向读取，不要读整个模块树）
2. 做最小修改
3. 跑变更相关的验证命令（参考 `tasks.json` 中对应 task 的 `verification_commands`）；必要时补全量门禁
4. 任一基础验证失败 → 该项标 BLOCKED，回退该项改动

### 证据要求

- 对每个 actionable `FAIL`/`WARN` 写明 finding id、修改文件、验证命令、退出码和证据路径。
- 若 finding 指向前端用户行为，必须补真实 UI 行为验证；只改 HTML 字符串或只跑 API 单测不能关闭前端 finding。
- 若 finding 指向隐私、打包、服务端持久化或客户端采集，必须补对应行为证据，不能只更新文档。

### 止损规则

- 同一个 finding 连续修复尝试 ≥3 次仍不通过，停止修复，标 BLOCKED。
- 环境/依赖级失败（`ImportError`、`ModuleNotFoundError`、conftest 无法导入等）标 BLOCKED，不要尝试修复测试框架或补缺失模块。

## Phase 4：提交

只暂存本节点修改的工作目录内源码文件并单独提交：

```bash
git add path/to/file1 path/to/file2 ...
git diff --cached --quiet || git commit -m "fix: address review findings"
```

**不要** `git add "$AO_ARTIFACTS_DIR/..."` —— artifacts 在 run 目录下，不在工作树内。不要 push，不要创建 PR。

## Phase 5：更新跟踪与产出

向 `$AO_ARTIFACTS_DIR/progress.md` 追加（不要回读全文，仅追加）：

```text
## {ISO Date} - Fix Warnings

**已修复**:
- {finding-id} - {一句话描述}

**BLOCKED**:
- {finding-id} - 原因: {简述}

---
```

写入修复报告 `$AO_ARTIFACTS_DIR/fix.md`：

```markdown
# Fix Warnings Report - {ISO Date}

## 输入摘要
- review-findings.json: FAIL={n} WARN={n}
- diff 范围: $base..HEAD

## 已修复
### {finding-id}: {标题}
- 来源: review-findings.json
- 修复说明: {最小改动描述}
- 变更文件: `path:line`
- 验证命令: `{command}` -> PASS

## BLOCKED
### {finding-id}
- 阻塞原因: {需架构判断 / 跨 story 重构 / 风险过高 / 需求不清 / 环境失败}
- 建议: {人工处理方向}

## 验证结果
| 命令 | 结果 | 摘要 |
| --- | --- | --- |

## 提交记录
- {commit hash} {message}（如无提交则写"未产生提交"）

## 最终结论
FIX_STATUS: FIXED / PARTIAL / NOT_NEEDED / BLOCKED
```

写入 `$AO_ARTIFACTS_DIR/fix-state.json`：

```json
{
  "status": "NO_ACTIONABLE_WARNINGS",
  "resolved_findings": [
    { "id": "...", "file": "...", "verification": "..." }
  ],
  "unresolved_findings": [
    { "id": "...", "reason": "BLOCKED: ..." }
  ],
  "verification": {
    "commands": [
      { "command": "...", "exit_code": 0, "evidence_path": "..." }
    ]
  }
}
```

状态判定：

- `NO_ACTIONABLE_WARNINGS`：所有 actionable finding 已关闭（剩余的都是 BLOCKED，不算 actionable）。
- `ACTIONABLE_FINDINGS_REMAIN`：还有 actionable finding 未关闭（loop 下一轮会继续处理）。

## Phase 6：收尾

最后只打印：

```text
FIX_FILE=$AO_ARTIFACTS_DIR/fix.md
FIX_STATUS={FIXED|PARTIAL|NOT_NEEDED|BLOCKED}
```

如果 `fix-state.json.status == NO_ACTIONABLE_WARNINGS`（所有 actionable finding 已关闭或剩余都是 BLOCKED），输出终止哨兵：

```text
<promise>NO_ACTIONABLE_WARNINGS</promise>
```

否则输出 `ACTIONABLE_FINDINGS_REMAIN`，loop 下一轮会继续处理。
