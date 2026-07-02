import json
from pathlib import Path

import pytest

from agentic_workflow.contract_gates import ContractGateError, validate_contract_artifact


def test_task_graph_contract_rejects_cycles(tmp_path: Path) -> None:
    path = tmp_path / "task-graph.json"
    path.write_text(
        json.dumps(
            {
                "tasks": [
                    _task("T-1", ["AC-1"], ["app"]),
                    _task("T-2", ["AC-1"], ["app"]),
                ],
                "edges": [{"from": "T-1", "to": "T-2"}, {"from": "T-2", "to": "T-1"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractGateError, match="cycle"):
        validate_contract_artifact(path, "task_graph_contract")


def test_task_graph_accepts_nodes_field(tmp_path: Path) -> None:
    """task-graph 用 'nodes' 字段（claude 常见生成形态）应通过验证。

    回归点：验证器曾只接受 'tasks' 字段，导致 claude 生成的 'nodes' 形态被误判为非法。
    task-graph 本质是依赖图，详细 task 信息由 tasks.json 验证。
    """
    path = tmp_path / "task-graph.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "T-1", "phase": 1, "priority": "P0"},
                    {"id": "T-2", "phase": 1, "priority": "P0"},
                ],
                "edges": [{"from": "T-1", "to": "T-2", "type": "hard_dependency"}],
            }
        ),
        encoding="utf-8",
    )

    validate_contract_artifact(path, "task_graph_contract")


def test_task_graph_accepts_null_target(tmp_path: Path) -> None:
    """to=null 的 edge 表示并行无依赖的 phase 标记，应被接受（不参与依赖图）。"""
    path = tmp_path / "task-graph.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "T-1", "phase": 1},
                    {"id": "T-2", "phase": 1},
                ],
                "edges": [
                    {"from": "T-1", "to": None, "type": "phase_parallel"},
                    {"from": "T-2", "to": None, "type": "phase_parallel"},
                ],
            }
        ),
        encoding="utf-8",
    )

    validate_contract_artifact(path, "task_graph_contract")


def test_task_graph_rejects_edge_to_unknown_task(tmp_path: Path) -> None:
    """to 指向未知 task id 的 edge 仍应报错。"""
    path = tmp_path / "task-graph.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "T-1"}],
                "edges": [{"from": "T-1", "to": "T-UNKNOWN"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractGateError, match="unknown task"):
        validate_contract_artifact(path, "task_graph_contract")


def test_small_scope_contract_rejects_privacy_change(tmp_path: Path) -> None:
    path = tmp_path / "small-scope.json"
    path.write_text(
        json.dumps(
            {
                "goal": "fix copy",
                "change_type": "bugfix",
                "observable_signal": "button disabled text",
                "allowed_files": ["src/view.tsx"],
                "forbidden_areas": ["data model", "privacy"],
                "requires_repro": True,
                "verification_commands": ["npm test"],
                "upgrade_triggers": ["new product behavior"],
                "max_components": 1,
                "data_model_change_allowed": False,
                "privacy_change_allowed": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractGateError, match="privacy"):
        validate_contract_artifact(path, "small_scope_contract")


def _task(task_id: str, acceptance: list[str], components: list[str]) -> dict[str, object]:
    return {
        "id": task_id,
        "acceptance_refs": acceptance,
        "component_refs": components,
        "verification_commands": ["pytest -q"],
        "done_signal": "tests pass",
    }


def _minimal_product_contract() -> dict[str, object]:
    return {
        "product_goal": "demo goal",
        "users": [{"role": "operator"}],
        "workflows": [{"id": "w1", "steps": ["s1"]}],
        "non_goals": ["g1"],
        "domain_objects": [{"name": "D1", "fields": []}],
        "states": [{"object": "D1", "transitions": []}],
        "frontend": {"framework": "React"},
        "backend": {"framework": "FastAPI"},
        "data": {"type": "SQLite"},
        "privacy": ["不存储原始敏感数据"],
        "security": ["路径模式匹配不读取文件内容"],
        "acceptance_items": [{"id": "ACC-1", "title": "t", "description": "d"}],
    }


def test_product_contract_accepts_privacy_as_list(tmp_path: Path) -> None:
    """privacy/security 作为字符串列表（agent 自然生成形态）应通过验证。

    回归点：验证器曾要求 _require_object（仅 dict），导致 agent 生成的 list
    形态被误判为非法。修复后 list 或 dict 均合法。
    """
    path = tmp_path / "product-contract.json"
    payload = _minimal_product_contract()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    validate_contract_artifact(path, "product_contract")


def test_product_contract_accepts_privacy_as_object(tmp_path: Path) -> None:
    """privacy/security 作为结构化对象仍应通过验证（向后兼容）。"""
    path = tmp_path / "product-contract.json"
    payload = _minimal_product_contract()
    payload["privacy"] = {"data_minimization": ["不存储原始数据"]}
    payload["security"] = {"validation": ["Luhn 校验"]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    validate_contract_artifact(path, "product_contract")


def test_product_contract_rejects_empty_privacy_list(tmp_path: Path) -> None:
    """privacy 为空列表仍应被拒绝，确保放宽形态不降低非空要求。"""
    path = tmp_path / "product-contract.json"
    payload = _minimal_product_contract()
    payload["privacy"] = []
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContractGateError, match="privacy"):
        validate_contract_artifact(path, "product_contract")


def _minimal_story(story_id: str, *, acceptance_ids: list[str] | None = None) -> dict[str, object]:
    payload = {
        "id": story_id,
        "title": "demo story",
        "user_value": "value",
        "acceptance_ids": ["ACC-1"] if acceptance_ids is None else acceptance_ids,
        "acceptance_criteria": ["criterion"],
        "technical_notes": ["note"],
        "depends_on": [],
        "priority": 1,
        "risk": "low",
        "required_evidence": ["evidence"],
        "passes": False,
        "status": "pending",
    }
    if acceptance_ids is None:
        payload.pop("acceptance_ids")
    return payload


def test_stories_contract_accepts_empty_acceptance_ids(tmp_path: Path) -> None:
    """支撑性 story（前端/infra/迁移）可能无直接对应 acceptance item，acceptance_ids 允许为空 list。

    回归点：验证器曾要求 acceptance_ids 非空，导致前端展示类 story 被误判为非法。
    通用工作流需适配各类项目，story 可验证性由 acceptance_criteria + required_evidence 保证。
    """
    path = tmp_path / "stories.json"
    payload = {"stories": [_minimal_story("S1", acceptance_ids=[])]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    validate_contract_artifact(path, "stories_contract")


def test_stories_contract_rejects_missing_acceptance_ids(tmp_path: Path) -> None:
    """acceptance_ids 字段缺失仍应报错，确保 story 显式声明 acceptance 关联（即使为空）。"""
    path = tmp_path / "stories.json"
    payload = {"stories": [_minimal_story("S1", acceptance_ids=None)]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContractGateError, match="acceptance_ids missing"):
        validate_contract_artifact(path, "stories_contract")


def test_stories_contract_accepts_non_empty_acceptance_ids(tmp_path: Path) -> None:
    """有对应 acceptance item 的 story 仍应使用非空 acceptance_ids（向后兼容）。"""
    path = tmp_path / "stories.json"
    payload = {"stories": [_minimal_story("S1", acceptance_ids=["ACC-1", "ACC-2"])]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    validate_contract_artifact(path, "stories_contract")


def _minimal_task(
    task_id: str,
    *,
    dependencies: list[str] | None = None,
    files_expected: list[str] | None = None,
    tests_required: list[str] | None = None,
) -> dict[str, object]:
    payload = {
        "id": task_id,
        "title": "demo task",
        "observable_outcome": "tests pass",
        "files_expected": ["backend/app/foo.py"] if files_expected is None else files_expected,
        "tests_required": ["backend/tests/test_foo.py"] if tests_required is None else tests_required,
        "verification_commands": ["pytest -q"],
        "done_signal": "TASK-PASS",
        "dependencies": [] if dependencies is None else dependencies,
        "risk": "low",
        "size": "S",
    }
    return payload


def test_tasks_contract_accepts_empty_dependencies(tmp_path: Path) -> None:
    """无依赖的并行 task（Phase 1 起始 task）dependencies 为空列表应通过验证。

    回归点：验证器曾用 _require_present 检查 dependencies，把空列表视为 empty 而误判，
    导致 spec-driven 工作流 generate-implementation-plan 节点的 tasks.json 被拒。
    """
    path = tmp_path / "tasks.json"
    payload = {"tasks": [_minimal_task("T-1", dependencies=[])]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    validate_contract_artifact(path, "tasks_contract")


def test_tasks_contract_accepts_empty_files_expected(tmp_path: Path) -> None:
    """数据库迁移类 task 不涉及源码文件，files_expected 为空列表应通过验证。"""
    path = tmp_path / "tasks.json"
    payload = {"tasks": [_minimal_task("T-DB-1", files_expected=[])]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    validate_contract_artifact(path, "tasks_contract")


def test_tasks_contract_accepts_empty_tests_required(tmp_path: Path) -> None:
    """验证汇总类 task 本身即验证入口，tests_required 为空列表应通过验证。"""
    path = tmp_path / "tasks.json"
    payload = {"tasks": [_minimal_task("T-VERIFY-1", tests_required=[])]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    validate_contract_artifact(path, "tasks_contract")


def test_tasks_contract_rejects_missing_dependencies(tmp_path: Path) -> None:
    """dependencies 字段缺失仍应报错，确保 task 显式声明依赖关系（即使为空）。"""
    path = tmp_path / "tasks.json"
    payload = _minimal_task("T-1")
    payload.pop("dependencies")
    path.write_text(json.dumps({"tasks": [payload]}, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContractGateError, match="missing dependencies"):
        validate_contract_artifact(path, "tasks_contract")


def test_tasks_contract_rejects_missing_observable_outcome(tmp_path: Path) -> None:
    """observable_outcome 字段缺失仍应报错，确保 task 绑定可观察结果。"""
    path = tmp_path / "tasks.json"
    payload = _minimal_task("T-1")
    payload.pop("observable_outcome")
    path.write_text(json.dumps({"tasks": [payload]}, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContractGateError, match="missing observable_outcome"):
        validate_contract_artifact(path, "tasks_contract")
