from pathlib import Path

from agentic_workflow.plan_gates import check_plan_artifact


def test_check_plan_artifact_passes_executable_plan(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_valid_plan(), encoding="utf-8")

    result = check_plan_artifact(plan)

    assert result.ok


def test_check_plan_artifact_fails_blocked_plan(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_valid_plan().replace("READY", "BLOCKED", 1), encoding="utf-8")

    result = check_plan_artifact(plan)

    assert not result.ok
    assert any("BLOCKED" in message for message in result.messages)


def test_check_plan_artifact_fails_missing_validate(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_valid_plan().replace("- **VERIFY**: `pytest -q`\n", ""), encoding="utf-8")

    result = check_plan_artifact(plan)

    assert not result.ok
    assert any("VERIFY" in message for message in result.messages)


def _valid_plan() -> str:
    return """# Plan: Example

## Status
READY

## Input Summary
目标明确。

## Scope and Non-goals
只做一个功能切片，不改变产品事实。

## Assumptions and Open Questions
无阻断问题。

## Architecture and Integration Decisions
使用现有 stack contract 和 `app` 组件。

## Task Graph
T-001 无依赖。

## Task Details

### Task T-001: 更新示例行为
- **ACCEPTANCE**: `AC-001`
- **COMPONENTS**: `app`
- **FILES**: `src/example.py`
- **TESTS**: `tests/test_example.py`
- **VERIFY**: `pytest -q`
- **DONE**: 行为可观察
- **DEPENDS**: none
- **SIZE**: S

## Verification Plan
运行 `pytest -q`。

## Acceptance Matrix
- `AC-001` -> T-001

## Risks
无。

## Stop Conditions
发现需要改变产品事实则停止。
"""
