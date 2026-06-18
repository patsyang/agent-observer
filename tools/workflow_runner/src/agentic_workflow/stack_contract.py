from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUSINESS_STACK_WORKFLOWS = {"small-change", "plan-execute", "spec-driven"}
STACK_CONTRACT_RELATIVE_PATH = Path(".agentic") / "stack-contract.json"


class StackContractError(ValueError):
    pass


@dataclass(frozen=True)
class StackContractRef:
    contract_id: str
    revision: int
    hash: str
    status: str
    path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "revision": self.revision,
            "hash": self.hash,
            "status": self.status,
            "path": self.path,
        }


@dataclass(frozen=True)
class StackContract:
    ref: StackContractRef
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return {"ref": self.ref.to_dict(), "payload": self.payload}


def stack_contract_required(workflow_name: str, *, is_project_run: bool) -> bool:
    return is_project_run and workflow_name in BUSINESS_STACK_WORKFLOWS


def load_stack_contract(project_root: Path, *, project_id: str | None = None) -> StackContract:
    path = project_root / STACK_CONTRACT_RELATIVE_PATH
    if not path.exists():
        raise StackContractError(
            f"missing project stack contract: {path}; run project stack confirm before business workflows"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise StackContractError(f"invalid stack contract JSON: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise StackContractError("stack contract must be a JSON object")
    _validate_payload(payload, project_id=project_id)
    contract_hash = _stable_hash(payload)
    ref = StackContractRef(
        contract_id=str(payload["contract_id"]),
        revision=int(payload.get("revision") or 1),
        hash=contract_hash,
        status=str(payload["status"]),
        path=str(path),
    )
    return StackContract(ref=ref, payload=payload)


def confirm_stack_contract(
    project_root: Path,
    *,
    source_path: Path,
    project_id: str | None = None,
) -> StackContract:
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise StackContractError(f"invalid stack contract JSON: {source_path}: {error}") from error
    if not isinstance(payload, dict):
        raise StackContractError("stack contract must be a JSON object")
    payload["status"] = "confirmed"
    if project_id and "project_id" not in payload:
        payload["project_id"] = project_id
    _validate_payload(payload, project_id=project_id)
    path = project_root / STACK_CONTRACT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return load_stack_contract(project_root, project_id=project_id)


def validate_stack_trace(path: Path, expected: StackContractRef) -> None:
    if not path.exists():
        raise StackContractError(f"missing stack-trace artifact: {path.name}")
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        refs = _collect_stack_refs(payload)
        if expected.hash not in refs["hashes"]:
            raise StackContractError(
                f"{path.name} does not reference stack contract hash {expected.hash}"
            )
        if expected.contract_id not in refs["ids"]:
            raise StackContractError(
                f"{path.name} does not reference stack contract id {expected.contract_id}"
            )
        return
    text = path.read_text(encoding="utf-8")
    if expected.hash not in text or expected.contract_id not in text:
        raise StackContractError(
            f"{path.name} must include stack contract id and hash"
        )


def validate_stack_acceptance_artifacts(
    artifacts_dir: Path,
    *,
    contract: StackContract,
    run_dir: Path,
) -> None:
    expected = contract.ref
    matrix_path = artifacts_dir / "acceptance-matrix.json"
    evidence_path = artifacts_dir / "component-evidence.json"
    coverage_path = artifacts_dir / "command-coverage.json"
    for path in (matrix_path, evidence_path, coverage_path):
        validate_stack_trace(path, expected)
    _validate_component_evidence(evidence_path, expected, contract.payload)
    _validate_command_coverage(coverage_path, expected, contract.payload)
    _validate_acceptance_evidence_paths(matrix_path, run_dir=run_dir)


def stack_runtime_env(contract: StackContract | None) -> dict[str, str]:
    if contract is None:
        return {}
    return {
        "AO_STACK_CONTRACT_PATH": contract.ref.path,
        "AO_STACK_CONTRACT_ID": contract.ref.contract_id,
        "AO_STACK_CONTRACT_HASH": contract.ref.hash,
        "AO_STACK_CONTRACT_REVISION": str(contract.ref.revision),
        "AO_STACK_CONTRACT_STATUS": contract.ref.status,
    }


def _validate_payload(payload: dict[str, Any], *, project_id: str | None) -> None:
    _required_text(payload, "contract_id")
    status = _required_text(payload, "status")
    if status != "confirmed":
        raise StackContractError("stack contract status must be confirmed")
    revision = payload.get("revision", 1)
    if not isinstance(revision, int) or revision < 1:
        raise StackContractError("stack contract revision must be a positive integer")
    if project_id:
        raw_project_id = payload.get("project_id")
        if raw_project_id is None:
            raise StackContractError("stack contract project_id is required")
        if str(raw_project_id) != project_id:
            raise StackContractError(
                f"stack contract project_id mismatch: expected {project_id}, got {raw_project_id}"
            )
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise StackContractError("stack contract components must be a non-empty array")
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise StackContractError(f"stack contract component #{index + 1} must be an object")
        _required_text(component, "component_id")
        _required_text(component, "kind")
        _required_text(component, "language")
        _required_text(component, "root")
    commands = payload.get("commands")
    if not isinstance(commands, dict):
        raise StackContractError("stack contract commands must be an object")
    verify_all = commands.get("verify_all")
    if not _is_command_list(verify_all):
        raise StackContractError("stack contract commands.verify_all must be a non-empty command list")


def _validate_component_evidence(
    path: Path,
    expected: StackContractRef,
    contract_payload: dict[str, Any],
) -> None:
    payload = _read_json_object(path)
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise StackContractError("component-evidence.json must include non-empty components")
    required_ids = {
        str(component["component_id"])
        for component in contract_payload.get("components", [])
        if isinstance(component, dict) and isinstance(component.get("component_id"), str)
    }
    observed_ids: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise StackContractError("component evidence item must be an object")
        observed_ids.add(_required_text(component, "component_id"))
        evidence = component.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise StackContractError(
                f"component {component.get('component_id')} must include evidence"
            )
    missing = required_ids - observed_ids
    if missing:
        raise StackContractError(
            "component-evidence.json missing contract components: " + ", ".join(sorted(missing))
        )
    validate_stack_trace(path, expected)


def _validate_command_coverage(
    path: Path,
    expected: StackContractRef,
    contract_payload: dict[str, Any],
) -> None:
    payload = _read_json_object(path)
    commands = payload.get("commands")
    if not isinstance(commands, list) or not commands:
        raise StackContractError("command-coverage.json must include non-empty commands")
    required_commands = _command_set(contract_payload.get("commands", {}).get("verify_all"))
    observed_commands: set[str] = set()
    for item in commands:
        if not isinstance(item, dict):
            raise StackContractError("command coverage item must be an object")
        _required_text(item, "name")
        observed_commands.add(_required_text(item, "command"))
        result = str(item.get("result") or "").upper()
        if result not in {"PASS", "SKIPPED_WITH_REASON"}:
            raise StackContractError(f"command coverage item is not passing: {item.get('name')}")
        if result == "SKIPPED_WITH_REASON":
            _required_text(item, "reason")
    missing = required_commands - observed_commands
    if missing:
        raise StackContractError(
            "command-coverage.json missing verify_all commands: " + ", ".join(sorted(missing))
        )
    validate_stack_trace(path, expected)


def _validate_acceptance_evidence_paths(path: Path, *, run_dir: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else payload.get("acceptance", [])
    if not isinstance(items, list) or not items:
        raise StackContractError("acceptance-matrix.json must include acceptance items")
    for item in items:
        if not isinstance(item, dict):
            raise StackContractError("acceptance item must be an object")
        evidence = item.get("evidence")
        entries = evidence if isinstance(evidence, list) else [evidence]
        for entry in entries:
            if isinstance(entry, dict):
                _ensure_evidence_path_exists(entry, run_dir=run_dir)


def _ensure_evidence_path_exists(entry: dict[str, Any], *, run_dir: Path) -> None:
    raw = (
        entry.get("path")
        or entry.get("log_path")
        or entry.get("artifact_path")
        or entry.get("evidence_path")
        or entry.get("source")
    )
    if raw is None:
        return
    if not isinstance(raw, str) or not raw.strip():
        raise StackContractError("evidence path must be a non-empty string")
    path = Path(raw)
    if not path.is_absolute():
        path = run_dir / path
    if not path.exists():
        raise StackContractError(f"evidence path does not exist: {path}")


def _collect_stack_refs(payload: Any) -> dict[str, set[str]]:
    ids: set[str] = set()
    hashes: set[str] = set()
    if isinstance(payload, dict):
        ref = payload.get("stack_contract_ref")
        if isinstance(ref, dict):
            raw_id = ref.get("contract_id")
            raw_hash = ref.get("hash")
            if isinstance(raw_id, str):
                ids.add(raw_id)
            if isinstance(raw_hash, str):
                hashes.add(raw_hash)
        for value in payload.values():
            nested = _collect_stack_refs(value)
            ids |= nested["ids"]
            hashes |= nested["hashes"]
    elif isinstance(payload, list):
        for value in payload:
            nested = _collect_stack_refs(value)
            ids |= nested["ids"]
            hashes |= nested["hashes"]
    return {"ids": ids, "hashes": hashes}


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StackContractError(f"{path.name} must be a JSON object")
    return payload


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StackContractError(f"stack contract field is required: {key}")
    return value


def _is_command_list(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _command_set(value: Any) -> set[str]:
    if isinstance(value, str) and value.strip():
        return {value.strip()}
    if isinstance(value, list):
        return {item.strip() for item in value if isinstance(item, str) and item.strip()}
    return set()
