from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contract_gates import validate_contract_artifact
from .models import ArtifactSpec


class ProductionGateError(RuntimeError):
    """Raised when a production-grade gate rejects a claimed pass."""


PLACEHOLDER_PATTERNS = (
    "<短标题>",
    "<目标>",
    "<待补充>",
    "TODO",
    "TBD",
    "占位",
    "这里填写",
    "实现相关功能",
    "处理相关逻辑",
    "正常工作",
    "提升体验",
)

META_PLACEHOLDER_CONTEXT = (
    "no ",
    "not found",
    "not contain",
    "without",
    "未发现",
    "不存在",
    "不包含",
    "禁止",
    "不得",
    "prohibit",
    "forbid",
    "扫描",
    "scan",
    "检查",
    "reviewed",
    "treated as allowed",
    "合法",
    "产品需求",
)

PASSING_GATE_RESULTS = {
    "PASS",
    "PASSED",
    "STABLE",
    "READY",
    "COMPLETE",
    "NO_ACTIONABLE_WARNINGS",
}


def select_next_story(stories: list[dict[str, Any]]) -> dict[str, Any] | None:
    passed = {_story_id(story) for story in stories if story.get("passes") is True}
    candidates = [
        story
        for story in stories
        if story.get("passes") is not True and set(_depends_on(story)) <= passed
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda story: (_priority(story), _story_id(story)))


def validate_acceptance_matrix(
    matrix_path: Path,
    *,
    run_dir: Path,
    review_path: Path | None = None,
    fix_path: Path | None = None,
) -> list[dict[str, Any]]:
    findings_requiring_closure = _review_findings_requiring_closure(review_path)
    if findings_requiring_closure and not _fix_loop_resolved_review(
        fix_path=fix_path,
        findings=findings_requiring_closure,
        run_dir=run_dir,
    ):
        raise ProductionGateError("review contains unresolved FAIL/WARN findings")

    payload = _read_json(matrix_path)
    if isinstance(payload, dict):
        result = str(payload.get("result") or "").strip().upper()
        if result and result != "PASS":
            raise ProductionGateError(f"acceptance matrix result is not PASS: {result}")
    items = _acceptance_items(payload)
    if not items:
        raise ProductionGateError("acceptance matrix must be a non-empty array")

    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ProductionGateError(f"acceptance item #{index + 1} must be an object")
        acceptance_id = _required_text(item, "acceptance_id")
        if acceptance_id in seen:
            raise ProductionGateError(f"duplicate acceptance_id: {acceptance_id}")
        seen.add(acceptance_id)
        if item.get("result") != "PASS":
            raise ProductionGateError(f"acceptance {acceptance_id} is not PASS")
        _required_text(item, "story_id")
        evidence = item.get("evidence")
        if not evidence:
            raise ProductionGateError(f"acceptance {acceptance_id} has no evidence")
        _validate_evidence_list(
            acceptance_id,
            evidence,
            run_dir=run_dir,
            behavior=str(item.get("behavior") or ""),
        )
    return items


def validate_frontend_template_selection(
    selection_path: Path,
    *,
    project_inspection_path: Path | None = None,
    production_spec_path: Path | None = None,
) -> None:
    payload = _read_json(selection_path)
    if not isinstance(payload, dict):
        raise ProductionGateError("frontend template selection must be a JSON object")
    frontend_required = payload.get("frontend_required", payload.get("requires_frontend"))
    if frontend_required is not True:
        return

    for key in (
        "template_id",
        "required_views",
        "required_components",
        "required_states",
        "required_interactions",
        "api_contracts",
        "e2e_scenarios",
        "visual_quality_rubric",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            if not value.strip():
                raise ProductionGateError(f"frontend selection missing {key}")
        elif not isinstance(value, list) or not value:
            raise ProductionGateError(f"frontend selection missing {key}")

    implementation = payload.get("frontend_implementation")
    if not isinstance(implementation, dict):
        implementation = payload.get("selected_stack")
    if not isinstance(implementation, dict):
        raise ProductionGateError("frontend selection missing frontend_implementation")

    mode = str(implementation.get("mode") or "").strip()
    if mode not in {
        "independent_frontend",
        "existing_frontend_adaptation",
        "server_rendered_equivalent",
    }:
        raise ProductionGateError("frontend implementation mode is not explicit")

    stack_source = str(implementation.get("stack_source") or "").strip()
    if stack_source not in {
        "project_existing",
        "spec_tech_stack",
        "project_standard",
        "user_confirmed",
        "product_contract",
    }:
        raise ProductionGateError("frontend implementation stack_source is not traceable")

    if mode == "server_rendered_equivalent" and not _server_rendered_exception_allowed(
        payload,
        project_inspection_path=project_inspection_path,
        production_spec_path=production_spec_path,
    ):
        raise ProductionGateError(
            "server-rendered frontend requires existing evidence or explicit product constraint"
        )

    if mode in {"independent_frontend", "existing_frontend_adaptation"}:
        _required_impl_text(implementation, "source_root")
        _required_impl_text(implementation, "framework")
        _required_impl_text(implementation, "language")
        _required_impl_text(implementation, "package_manager")
        _required_impl_text(implementation, "package_manifest")
        _required_command_list(implementation, "test_commands")
        _required_command_list(implementation, "build_commands")
        _required_command_list(implementation, "e2e_commands")

    if mode == "server_rendered_equivalent":
        _required_impl_text(implementation, "source_root")
        _required_command_list(implementation, "test_commands")
        _required_command_list(implementation, "e2e_commands")
        if not implementation.get("quality_equivalence"):
            raise ProductionGateError(
                "server-rendered frontend must declare quality_equivalence"
            )


def validate_required_artifact_specs(
    specs: list[ArtifactSpec],
    *,
    artifacts_dir: Path,
) -> None:
    for spec in specs:
        path = artifacts_dir / spec.path
        if not path.exists():
            raise ProductionGateError(f"missing required artifact: {spec.path}")
        if path.is_file() and path.stat().st_size == 0:
            raise ProductionGateError(f"empty required artifact: {spec.path}")
        if spec.kind == "json" or spec.path.endswith(".json"):
            _read_json(path)
        if "gate_pass" in spec.validators:
            _validate_gate_pass(path)
        for validator in spec.validators:
            if validator.endswith("_contract"):
                validate_contract_artifact(path, validator)
        if "non_placeholder" in spec.validators or spec.kind == "markdown":
            _reject_placeholders(path)


def _reject_placeholders(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        for pattern in PLACEHOLDER_PATTERNS:
            if pattern not in line:
                continue
            if _allowed_placeholder_reference(line):
                continue
            raise ProductionGateError(f"artifact {path.name} contains placeholder: {pattern}")


def _allowed_placeholder_reference(line: str) -> bool:
    normalized = line.strip().lower().replace("`", "")
    return any(marker in normalized for marker in META_PLACEHOLDER_CONTEXT)


def _validate_gate_pass(path: Path) -> None:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ProductionGateError(f"gate artifact {path.name} must be a JSON object")
    raw_result = payload.get("result", payload.get("status", payload.get("decision")))
    result = str(raw_result or "").strip().upper()
    if result not in PASSING_GATE_RESULTS:
        raise ProductionGateError(f"gate artifact {path.name} is not passing: {raw_result}")


def _acceptance_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("acceptance"), list):
        return payload["acceptance"]
    if isinstance(payload, dict) and isinstance(payload.get("acceptance_items"), list):
        return payload["acceptance_items"]
    raise ProductionGateError("acceptance matrix must be a non-empty array")


def _validate_evidence_list(
    acceptance_id: str,
    evidence: Any,
    *,
    run_dir: Path,
    behavior: str = "",
) -> None:
    if isinstance(evidence, dict):
        _validate_structured_evidence(
            acceptance_id,
            evidence,
            run_dir=run_dir,
            behavior=behavior,
        )
        return
    if not isinstance(evidence, list):
        raise ProductionGateError(f"acceptance {acceptance_id} has no evidence")

    has_behavioral_evidence = False
    screenshot_only = len(evidence) == 1 and _evidence_type(evidence[0]) == "screenshot"
    if screenshot_only:
        raise ProductionGateError(f"acceptance {acceptance_id} has screenshot-only proof")

    for index, entry in enumerate(evidence):
        if not isinstance(entry, dict):
            raise ProductionGateError(
                f"acceptance {acceptance_id} evidence #{index + 1} must be an object"
            )
        evidence_type = _evidence_type(entry)
        if evidence_type == "command":
            if int(entry.get("exit_code", -1)) != 0:
                raise ProductionGateError(f"acceptance {acceptance_id} command evidence failed")
            _resolve_evidence_path(entry, run_dir=run_dir)
            has_behavioral_evidence = True
        elif evidence_type == "playwright":
            assertions = entry.get("assertions")
            if not isinstance(assertions, list) or not assertions:
                raise ProductionGateError(
                    f"acceptance {acceptance_id} Playwright evidence has no assertions"
                )
            _resolve_evidence_path(entry, run_dir=run_dir)
            has_behavioral_evidence = True
        elif evidence_type in {"screenshot", "artifact", "scan", "policy"}:
            _resolve_evidence_path(entry, run_dir=run_dir)
        else:
            raise ProductionGateError(
                f"acceptance {acceptance_id} unsupported evidence type: {evidence_type}"
            )

    if not has_behavioral_evidence:
        raise ProductionGateError(f"acceptance {acceptance_id} lacks behavioral evidence")


def _validate_structured_evidence(
    acceptance_id: str,
    evidence: dict[str, Any],
    *,
    run_dir: Path,
    behavior: str = "",
) -> None:
    if evidence.get("screenshot_only") is True:
        raise ProductionGateError(f"acceptance {acceptance_id} has screenshot-only proof")

    has_behavioral_evidence = False
    commands = evidence.get("commands")
    if isinstance(commands, list):
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                raise ProductionGateError(
                    f"acceptance {acceptance_id} command evidence #{index + 1} must be an object"
                )
            if int(command.get("exit_code", -1)) != 0:
                raise ProductionGateError(f"acceptance {acceptance_id} command evidence failed")
            _resolve_evidence_path(command, run_dir=run_dir)
            has_behavioral_evidence = True

    raw_paths = evidence.get("paths")
    if isinstance(raw_paths, list):
        for raw_path in raw_paths:
            _resolve_raw_evidence_path(raw_path, run_dir=run_dir)

    evidence_types = evidence.get("evidence_types")
    if isinstance(evidence_types, list) and "playwright" in evidence_types:
        assertions = evidence.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            raise ProductionGateError(
                f"acceptance {acceptance_id} Playwright evidence has no assertions"
            )
        has_behavioral_evidence = True

    if _looks_like_ui_behavior(behavior):
        _validate_ui_behavior_evidence(acceptance_id, evidence)

    if not has_behavioral_evidence:
        raise ProductionGateError(f"acceptance {acceptance_id} lacks behavioral evidence")


def _resolve_evidence_path(entry: dict[str, Any], *, run_dir: Path) -> Path:
    raw_path = (
        entry.get("path")
        or entry.get("log_path")
        or entry.get("screenshot_path")
        or entry.get("artifact_path")
        or entry.get("evidence_path")
        or entry.get("source")
    )
    return _resolve_raw_evidence_path(raw_path, run_dir=run_dir)


def _resolve_raw_evidence_path(raw_path: Any, *, run_dir: Path) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ProductionGateError("evidence path is required")
    path = Path(raw_path)
    if not path.is_absolute():
        path = run_dir / path
    if not path.exists():
        raise ProductionGateError(f"evidence path does not exist: {path}")
    return path


def _review_findings_requiring_closure(review_path: Path | None) -> list[str]:
    if not review_path or not review_path.exists():
        return []
    if review_path.suffix.lower() == ".json":
        payload = _read_json(review_path)
        if isinstance(payload, dict):
            findings = payload.get("findings")
            if isinstance(findings, list):
                return [
                    str(finding.get("id") or "").strip()
                    for finding in findings
                    if isinstance(finding, dict)
                    and str(finding.get("severity") or "").strip().upper() in {"FAIL", "WARN"}
                    and str(finding.get("id") or "").strip()
                ]
            counts = payload.get("counts")
            if isinstance(counts, dict) and int(counts.get("fail") or 0) > 0:
                return ["__UNKNOWN_REVIEW_FAILURE__"]
        return []

    text = review_path.read_text(encoding="utf-8")
    table_count = _count_table_status(text, "FAIL")
    if table_count is not None:
        return ["__UNKNOWN_REVIEW_FAILURE__"] if table_count > 0 else []
    return ["__UNKNOWN_REVIEW_FAILURE__"] if re.search(r"\bFAIL\b", text) else []


def _fix_loop_resolved_review(
    *,
    fix_path: Path | None,
    findings: list[str],
    run_dir: Path,
) -> bool:
    if not fix_path or not fix_path.exists():
        return False
    text = fix_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        status = str(payload.get("status") or "").strip().upper()
        unresolved = payload.get("unresolved_findings")
        if status != "NO_ACTIONABLE_WARNINGS" or unresolved != []:
            return False
        resolved_ids = _resolved_finding_ids(payload)
        if not set(findings) <= resolved_ids:
            return False
        return _resolved_findings_have_passing_evidence(payload, run_dir=run_dir)
    return bool(re.search(r"\bNO_ACTIONABLE_WARNINGS\b", text))


def _resolved_finding_ids(payload: dict[str, Any]) -> set[str]:
    resolved = payload.get("resolved_findings")
    if not isinstance(resolved, list):
        return set()
    ids: set[str] = set()
    for finding in resolved:
        if isinstance(finding, dict) and isinstance(finding.get("id"), str):
            ids.add(finding["id"])
    return ids


def _resolved_findings_have_passing_evidence(
    payload: dict[str, Any],
    *,
    run_dir: Path,
) -> bool:
    resolved = payload.get("resolved_findings")
    if not isinstance(resolved, list):
        return False
    for finding in resolved:
        if not isinstance(finding, dict):
            return False
        verification = finding.get("verification")
        if not isinstance(verification, list) or not verification:
            return False
        for entry in verification:
            if not isinstance(entry, dict):
                return False
            if int(entry.get("exit_code", -1)) != 0:
                return False
            try:
                _resolve_evidence_path(entry, run_dir=run_dir)
            except ProductionGateError:
                return False
    return True


def _looks_like_ui_behavior(behavior: str) -> bool:
    normalized = behavior.lower()
    return any(
        marker in normalized
        for marker in (
            "dashboard",
            "ui",
            "browser",
            "rendered",
            "product surface",
            "form",
            "viewport",
        )
    )


def _validate_ui_behavior_evidence(acceptance_id: str, evidence: dict[str, Any]) -> None:
    evidence_types = {
        str(item).strip().lower()
        for item in evidence.get("evidence_types", [])
        if isinstance(item, str)
    }
    if not evidence_types & {"browser", "playwright", "ui"}:
        raise ProductionGateError(f"acceptance {acceptance_id} lacks browser/UI evidence")

    browser = evidence.get("browser")
    if not isinstance(browser, dict):
        if "playwright" in evidence_types and evidence.get("assertions"):
            return
        raise ProductionGateError(f"acceptance {acceptance_id} lacks browser/UI assertions")
    if browser.get("screenshot_only") is True:
        raise ProductionGateError(f"acceptance {acceptance_id} has screenshot-only proof")
    has_action = any(
        browser.get(key) is True
        for key in ("submitted_form", "clicked", "user_action", "navigated", "persisted_state")
    )
    assertions = browser.get("assertions")
    if not has_action and not (isinstance(assertions, list) and assertions):
        raise ProductionGateError(f"acceptance {acceptance_id} lacks browser/UI assertions")


def _server_rendered_exception_allowed(
    selection: dict[str, Any],
    *,
    project_inspection_path: Path | None,
    production_spec_path: Path | None,
) -> bool:
    inspection = _read_optional_json(project_inspection_path)
    frontend = inspection.get("frontend") if isinstance(inspection, dict) else None
    if isinstance(frontend, dict):
        if frontend.get("server_rendered") is True or frontend.get("existing_server_rendered") is True:
            return True
        framework = str(frontend.get("framework") or frontend.get("kind") or "").lower()
        if "server" in framework and "render" in framework:
            return True

    exception = selection.get("server_rendered_exception")
    if not isinstance(exception, dict):
        return False
    source = str(exception.get("constraint_source") or "").strip()
    explicit = exception.get("explicit_product_constraint") is True
    if source not in {"product_contract", "production_spec", "user_confirmed"} or not explicit:
        return False

    reason = str(exception.get("rationale") or "").strip()
    if len(reason) < 30:
        return False

    if source == "production_spec" and production_spec_path and production_spec_path.exists():
        text = production_spec_path.read_text(encoding="utf-8").lower()
        return any(marker in text for marker in ("server-rendered", "server rendered", "single binary"))
    return True


def _read_optional_json(path: Path | None) -> Any:
    if not path or not path.exists():
        return {}
    return _read_json(path)


def _required_impl_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductionGateError(f"frontend implementation missing {key}")
    return value


def _required_command_list(payload: dict[str, Any], key: str) -> None:
    value = payload.get(key)
    if isinstance(value, str):
        if value.strip():
            return
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        if value:
            return
    raise ProductionGateError(f"frontend implementation missing {key}")


def _count_table_status(text: str, label: str) -> int | None:
    match = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*(\d+)\s*\|", text)
    return int(match.group(1)) if match else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProductionGateError(f"invalid JSON: {path}: {error}") from error


def _required_text(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductionGateError(f"{key} is required")
    return value


def _story_id(story: dict[str, Any]) -> str:
    value = story.get("id")
    return value if isinstance(value, str) else ""


def _depends_on(story: dict[str, Any]) -> list[str]:
    value = story.get("depends_on", story.get("dependsOn", []))
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _priority(story: dict[str, Any]) -> int:
    value = story.get("priority")
    return value if isinstance(value, int) else 1_000_000


def _evidence_type(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    value = entry.get("type")
    if isinstance(value, str):
        return value
    if isinstance(entry.get("command"), str) and "exit_code" in entry:
        return "command"
    if isinstance(entry.get("assertions"), list):
        return "playwright"
    return ""
