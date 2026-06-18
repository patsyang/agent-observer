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
