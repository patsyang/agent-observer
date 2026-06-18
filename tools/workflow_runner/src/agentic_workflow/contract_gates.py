from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ContractGateError(RuntimeError):
    """Raised when workflow contract artifacts are structurally invalid."""


def validate_contract_artifact(path: Path, validator: str) -> None:
    if validator == "product_contract":
        validate_product_contract(_read_json_object(path))
        return
    if validator == "stories_contract":
        validate_stories(_read_json_object_or_list(path))
        return
    if validator == "tasks_contract":
        validate_tasks(_read_json_object_or_list(path))
        return
    if validator == "task_graph_contract":
        validate_task_graph(_read_json_object(path))
        return
    if validator == "small_scope_contract":
        validate_small_scope(_read_json_object(path))
        return
    if validator == "verification_contract":
        validate_verification(_read_json_object(path))
        return
    raise ContractGateError(f"unsupported contract validator: {validator}")


def validate_product_contract(payload: dict[str, Any]) -> None:
    for key in (
        "product_goal",
        "users",
        "workflows",
        "non_goals",
        "domain_objects",
        "states",
        "frontend",
        "backend",
        "data",
        "privacy",
        "security",
        "acceptance_items",
    ):
        _require_present(payload, key, "product-contract")
    _require_non_empty_list(payload["users"], "product-contract.users")
    _require_non_empty_list(payload["workflows"], "product-contract.workflows")
    _require_non_empty_list(payload["acceptance_items"], "product-contract.acceptance_items")
    _require_object(payload["privacy"], "product-contract.privacy")
    _require_object(payload["security"], "product-contract.security")


def validate_stories(payload: Any) -> None:
    stories = _items(payload, "stories")
    if not stories:
        raise ContractGateError("stories must contain at least one story")
    ids: set[str] = set()
    for index, story in enumerate(stories, start=1):
        if not isinstance(story, dict):
            raise ContractGateError(f"stories[{index}] must be an object")
        story_id = _require_text(story, "id", f"stories[{index}]")
        if story_id in ids:
            raise ContractGateError(f"duplicate story id: {story_id}")
        ids.add(story_id)
        for key in ("title", "user_value", "acceptance_criteria", "required_evidence", "status"):
            _require_present(story, key, story_id)
        _require_non_empty_list(story.get("acceptance_ids"), f"{story_id}.acceptance_ids")
        depends_on = story.get("depends_on", [])
        if not isinstance(depends_on, list):
            raise ContractGateError(f"{story_id}.depends_on must be a list")
    for story in stories:
        for dependency in story.get("depends_on", []):
            if dependency not in ids:
                raise ContractGateError(f"{story['id']} depends on unknown story {dependency}")


def validate_tasks(payload: Any) -> None:
    tasks = _items(payload, "tasks")
    if not tasks:
        raise ContractGateError("tasks must contain at least one task")
    ids: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ContractGateError(f"tasks[{index}] must be an object")
        task_id = _require_text(task, "id", f"tasks[{index}]")
        if task_id in ids:
            raise ContractGateError(f"duplicate task id: {task_id}")
        ids.add(task_id)
        for key in (
            "title",
            "observable_outcome",
            "files_expected",
            "tests_required",
            "verification_commands",
            "done_signal",
            "dependencies",
            "risk",
            "size",
        ):
            _require_present(task, key, task_id)
        if str(task.get("size")).upper() in {"L", "XL"}:
            raise ContractGateError(f"{task_id}.size must be S or M")
        _require_non_empty_list(task.get("verification_commands"), f"{task_id}.verification_commands")
        _require_non_empty_text_or_list(task.get("done_signal"), f"{task_id}.done_signal")


def validate_task_graph(payload: dict[str, Any]) -> None:
    tasks = payload.get("tasks")
    edges = payload.get("edges", [])
    if not isinstance(tasks, list) or not tasks:
        raise ContractGateError("task-graph.tasks must be a non-empty list")
    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ContractGateError("task-graph.tasks entries must be objects")
        ids.add(_require_text(task, "id", "task-graph task"))
        _require_non_empty_list(task.get("verification_commands"), f"{task['id']}.verification_commands")
        _require_non_empty_text_or_list(task.get("done_signal"), f"{task['id']}.done_signal")
        if not task.get("component_refs"):
            raise ContractGateError(f"{task['id']}.component_refs is required")
        if not task.get("acceptance_refs"):
            raise ContractGateError(f"{task['id']}.acceptance_refs is required")
    if not isinstance(edges, list):
        raise ContractGateError("task-graph.edges must be a list")
    graph = {task_id: set() for task_id in ids}
    for edge in edges:
        if not isinstance(edge, dict):
            raise ContractGateError("task-graph.edges entries must be objects")
        source = _require_text(edge, "from", "task-graph edge")
        target = _require_text(edge, "to", "task-graph edge")
        if source not in ids or target not in ids:
            raise ContractGateError(f"task-graph edge references unknown task: {source}->{target}")
        graph[target].add(source)
    _reject_cycles(graph)


def validate_small_scope(payload: dict[str, Any]) -> None:
    for key in (
        "goal",
        "change_type",
        "observable_signal",
        "allowed_files",
        "forbidden_areas",
        "requires_repro",
        "verification_commands",
        "upgrade_triggers",
        "max_components",
        "data_model_change_allowed",
        "privacy_change_allowed",
    ):
        _require_present(payload, key, "small-scope")
    _require_non_empty_list(payload["verification_commands"], "small-scope.verification_commands")
    if int(payload["max_components"]) > 1:
        raise ContractGateError("small-scope.max_components must be 1 or less")
    if payload["data_model_change_allowed"] is not False:
        raise ContractGateError("small-change cannot allow data model changes")
    if payload["privacy_change_allowed"] is not False:
        raise ContractGateError("small-change cannot allow privacy changes")


def validate_verification(payload: dict[str, Any]) -> None:
    for key in ("commands", "expected_results", "regression_tests"):
        _require_present(payload, key, "verification")
    _require_non_empty_list(payload["commands"], "verification.commands")
    _require_non_empty_list(payload["expected_results"], "verification.expected_results")


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ContractGateError(f"{path.name} must be a JSON object")
    return payload


def _read_json_object_or_list(path: Path) -> Any:
    payload = _read_json(path)
    if not isinstance(payload, (dict, list)):
        raise ContractGateError(f"{path.name} must be a JSON object or array")
    return payload


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ContractGateError(f"invalid JSON: {path}: {error}") from error


def _items(payload: Any, key: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    value = payload.get(key) if isinstance(payload, dict) else None
    if isinstance(value, list):
        return value
    raise ContractGateError(f"{key} must be a list")


def _require_present(payload: dict[str, Any], key: str, label: str) -> Any:
    if key not in payload:
        raise ContractGateError(f"{label} missing {key}")
    value = payload[key]
    if value is None or value == "" or value == [] or value == {}:
        raise ContractGateError(f"{label}.{key} must not be empty")
    return value


def _require_text(payload: dict[str, Any], key: str, label: str) -> str:
    value = _require_present(payload, key, label)
    if not isinstance(value, str) or not value.strip():
        raise ContractGateError(f"{label}.{key} must be non-empty text")
    return value


def _require_object(value: Any, label: str) -> None:
    if not isinstance(value, dict) or not value:
        raise ContractGateError(f"{label} must be a non-empty object")


def _require_non_empty_list(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ContractGateError(f"{label} must be a non-empty list")


def _require_non_empty_text_or_list(value: Any, label: str) -> None:
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, list) and value:
        return
    raise ContractGateError(f"{label} must be non-empty text or list")


def _reject_cycles(graph: dict[str, set[str]]) -> None:
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node: str) -> None:
        if node in permanent:
            return
        if node in temporary:
            raise ContractGateError(f"task graph has a dependency cycle at {node}")
        temporary.add(node)
        for dependency in graph[node]:
            visit(dependency)
        temporary.remove(node)
        permanent.add(node)

    for node in graph:
        visit(node)
