from __future__ import annotations

import json
import hashlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .infra import load_manifest, plan_update
from .infra import read_lock
from .infra_files import iter_managed_files, iter_template_files, normalize_path, sha256_file
from .models import RunContext
from .subprocess_utils import run_command


CONTROL_PLANE_WORKFLOW = "control-plane-change"
STATUS_FAILED = "FAILED"
STATUS_NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
STATUS_PASSED = "PASSED"


@dataclass(frozen=True)
class InfraChangedPath:
    path: str
    status: str
    old_path: str | None = None

    def key(self) -> tuple[str, str, str | None]:
        return (self.path, self.status, self.old_path)

    def to_dict(self) -> dict[str, str | None]:
        return {"path": self.path, "status": self.status, "old_path": self.old_path}


@dataclass(frozen=True)
class InfraRiskProfile:
    categories: tuple[str, ...]
    high_risk: bool
    requires_review: bool
    requires_runner_tests: bool
    requires_entrypoint_smoke: bool
    requires_template_lock_gate: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "categories": list(self.categories),
            "high_risk": self.high_risk,
            "requires_review": self.requires_review,
            "requires_runner_tests": self.requires_runner_tests,
            "requires_entrypoint_smoke": self.requires_entrypoint_smoke,
            "requires_template_lock_gate": self.requires_template_lock_gate,
        }


@dataclass(frozen=True)
class ControlPlaneGateResult:
    return_code: int
    status: str
    verification: str
    changed_files: list[str]


class ControlPlaneGateError(RuntimeError):
    def __init__(self, reason: str, *, status: str = STATUS_FAILED) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


def finalize_control_plane_run(
    context: RunContext,
    *,
    skip_verify: bool,
    timeout_seconds: int = 180,
) -> ControlPlaneGateResult:
    gate_dir = context.run_dir / "gate-results"
    gate_dir.mkdir(parents=True, exist_ok=True)
    try:
        pre_changed = implementation_changed_set(context)
        _write_json(gate_dir / "changed-set.json", {"paths": [item.to_dict() for item in pre_changed]})
        _validate_changed_files_artifact(context, pre_changed)
        _validate_forbidden_paths(pre_changed)

        risk = risk_profile(context, pre_changed)
        _write_json(gate_dir / "risk-profile.json", risk.to_dict())

        template_result = validate_template_lock_gate(context, pre_changed, risk)
        _write_json(gate_dir / "template-lock-gate.json", template_result)

        review_result = validate_review_gate(context, risk)
        _write_json(gate_dir / "review-gate.json", review_result)

        verification_result, verification_text, verification_status = run_verification_gate(
            context,
            risk,
            pre_changed=pre_changed,
            skip_verify=skip_verify,
            timeout_seconds=timeout_seconds,
        )
        _write_json(gate_dir / "verification.json", verification_result)

        if verification_status == STATUS_NEEDS_VERIFICATION:
            acceptance = {
                "result": "NEEDS_VERIFICATION",
                "run_id": context.run_id,
                "completion_allowed": False,
                "generated_by": "workflow_runner",
            }
            _write_json(context.run_dir / "infra-acceptance.json", acceptance)
            return ControlPlaneGateResult(
                return_code=3,
                status=STATUS_NEEDS_VERIFICATION,
                verification=verification_text,
                changed_files=[item.path for item in pre_changed],
            )

        acceptance = {
            "result": "PASS",
            "run_id": context.run_id,
            "changed_set_gate": "PASS",
            "template_lock_gate": "PASS",
            "verification_gate": "PASS",
            "review_gate": "PASS",
            "skip_verify": skip_verify,
            "completion_allowed": True,
            "generated_by": "workflow_runner",
        }
        _write_json(context.run_dir / "infra-acceptance.json", acceptance)
        return ControlPlaneGateResult(
            return_code=0,
            status=STATUS_PASSED,
            verification=verification_text,
            changed_files=[item.path for item in pre_changed],
        )
    except ControlPlaneGateError as error:
        _write_json(
            gate_dir / "failure.json",
            {"result": "FAIL", "reason": error.reason, "status": error.status},
        )
        return ControlPlaneGateResult(
            return_code=3 if error.status == STATUS_NEEDS_VERIFICATION else 1,
            status=error.status,
            verification=f"control-plane gate failed: {error.reason}",
            changed_files=[item.path for item in implementation_changed_set(context)],
        )


def implementation_changed_set(context: RunContext) -> list[InfraChangedPath]:
    return [
        item
        for item in git_changed_set(context.repo_root)
        if not _is_runner_generated_path(context, item.path)
    ]


def git_changed_set(repo_root: Path) -> list[InfraChangedPath]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ControlPlaneGateError(f"git_status_failed: {result.stderr.strip() or result.stdout.strip()}")
    tokens = [token for token in result.stdout.split("\0") if token]
    changed: list[InfraChangedPath] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if len(token) < 3:
            index += 1
            continue
        xy = token[:2]
        raw_path = normalize_path(token[3:])
        if xy == "??":
            changed.append(InfraChangedPath(path=raw_path, status="untracked"))
            index += 1
            continue
        if "U" in xy or xy in {"AA", "DD"}:
            raise ControlPlaneGateError("unmerged_git_status_not_supported")
        if xy[0] in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise ControlPlaneGateError("ambiguous_git_status")
            old_path = normalize_path(tokens[index + 1])
            changed.append(
                InfraChangedPath(
                    path=raw_path,
                    status="renamed" if xy[0] == "R" else "copied",
                    old_path=old_path,
                )
            )
            index += 2
            continue
        changed.append(InfraChangedPath(path=raw_path, status=_status_from_xy(xy)))
        index += 1
    return changed


def risk_profile(context: RunContext, changed: list[InfraChangedPath]) -> InfraRiskProfile:
    managed = managed_paths(context.repo_root)
    managed_prefixes = managed_directory_prefixes(context.repo_root)
    template_prefixes = managed_directory_template_prefixes(context.repo_root)
    categories: set[str] = set()
    for item in changed:
        path = item.path
        if path.startswith("apps/"):
            categories.add("forbidden_business_app")
        if path == "scripts/ao.py":
            categories.add("entrypoint")
        if path.startswith("tools/workflow_runner/"):
            categories.add("runner_core")
        if path.startswith("tools/workflow_runner/src/agentic_workflow/adapters/"):
            categories.add("runtime_adapter")
        if path.startswith(".agentic/workflow/definitions/"):
            categories.add("workflow_definition")
        if path.startswith(".agentic/workflow/") or path.startswith("commands/") or path.startswith(".codex/skills/"):
            categories.add("command_skill_contract")
        if (
            path in managed
            or any(path.startswith(prefix) for prefix in managed_prefixes)
            or any(path.startswith(prefix) for prefix in template_prefixes)
            or path.startswith("agentic-infra/templates/project/")
            or path in {"agentic-infra/manifest.json", "agentic.lock.json"}
        ):
            categories.add("infra_template")
    high_risk = bool(
        categories
        & {"runner_core", "runtime_adapter", "workflow_definition", "entrypoint", "infra_template"}
    )
    return InfraRiskProfile(
        categories=tuple(sorted(categories or {"docs_only"})),
        high_risk=high_risk,
        requires_review=high_risk,
        requires_runner_tests=bool(categories & {"runner_core", "runtime_adapter", "entrypoint"}),
        requires_entrypoint_smoke="entrypoint" in categories,
        requires_template_lock_gate="infra_template" in categories,
    )


def managed_paths(repo_root: Path) -> set[str]:
    try:
        manifest = load_manifest(repo_root)
    except ValueError:
        return set()
    return {entry.path for entry in iter_managed_files(repo_root, manifest)}


def managed_directory_prefixes(repo_root: Path) -> tuple[str, ...]:
    try:
        manifest = load_manifest(repo_root)
    except ValueError:
        return ()
    return tuple(
        normalize_path(directory["path"]).rstrip("/") + "/"
        for directory in manifest.get("managed_directories", [])
    )


def managed_directory_template_prefixes(repo_root: Path) -> tuple[str, ...]:
    try:
        manifest = load_manifest(repo_root)
    except ValueError:
        return ()
    template_root = normalize_path(manifest["template_root"]).rstrip("/")
    return tuple(f"{template_root}/{prefix}" for prefix in managed_directory_prefixes(repo_root))


def validate_template_lock_gate(
    context: RunContext,
    changed: list[InfraChangedPath],
    risk: InfraRiskProfile,
) -> dict[str, object]:
    if not risk.requires_template_lock_gate:
        return {"result": "PASS", "checked": False}
    changed_paths = {item.path for item in changed}
    managed = managed_paths(context.repo_root)
    deleted_managed = sorted(
        item.path for item in changed if item.status == "deleted" and item.path in managed
    )
    if deleted_managed:
        raise ControlPlaneGateError(
            "managed_file_deleted_without_manifest_change: " + ", ".join(deleted_managed)
        )
    plan = plan_update(project_root=context.repo_root, infra_root=context.repo_root)
    drifted = [item for item in plan["items"] if item["status"] != "unchanged"]
    if drifted:
        raise ControlPlaneGateError(
            "template_lock_gate_failed: "
            + ", ".join(f"{item['path']}={item['status']}" for item in drifted[:10])
        )
    unknown_templates = sorted(
        item.path
        for item in changed
        if item.status != "deleted"
        and item.path.startswith("agentic-infra/templates/project/")
        and not _template_path_is_manifested(context.repo_root, item.path)
    )
    if unknown_templates:
        raise ControlPlaneGateError("new_template_not_manifested: " + ", ".join(unknown_templates))
    directory_mismatches = _managed_directory_mismatches(context.repo_root, changed_paths)
    if directory_mismatches:
        raise ControlPlaneGateError(
            "managed_directory_template_lock_mismatch: " + ", ".join(directory_mismatches[:10])
        )
    return {"result": "PASS", "checked": True, "summary": plan["summary"]}


def validate_review_gate(context: RunContext, risk: InfraRiskProfile) -> dict[str, object]:
    if not risk.requires_review:
        return {"result": "PASS", "required": False}
    review_dir = context.run_dir / "review"
    raw_path = review_dir / "raw-findings.json"
    output_path = review_dir / "output.md"
    if not raw_path.exists() or not output_path.exists():
        raise ControlPlaneGateError("missing_critical_review")
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("kind") != "sub_agent" or not reviewer.get("agent_id"):
        raise ControlPlaneGateError("invalid_review_receipt")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ControlPlaneGateError("invalid_review_raw_findings")
    counts = {"p0": 0, "p1": 0, "p2": 0}
    for finding in findings:
        if not isinstance(finding, dict):
            raise ControlPlaneGateError("invalid_review_finding")
        severity = str(finding.get("severity", "")).lower()
        if severity in counts:
            counts[severity] += 1
        if severity in {"p0", "p1"}:
            raise ControlPlaneGateError("review_has_blocking_findings")
        if severity == "p2" and finding.get("disposition") not in {
            "fixed",
            "accepted_non_blocking",
            "documented_follow_up",
        }:
            raise ControlPlaneGateError("review_has_unhandled_p2")
    output = output_path.read_text(encoding="utf-8")
    if any(marker in output for marker in ("P0", "P1", "P2")) and not findings:
        raise ControlPlaneGateError("review_output_raw_findings_mismatch")
    receipt = {
        "reviewer_kind": "sub_agent",
        "provider": "external_review_receipt",
        "agent_id": reviewer.get("agent_id"),
        "raw_findings_path": str(raw_path),
        "output_path": str(output_path),
        "counts": counts,
        "findings": findings,
        "generated_by": "workflow_runner",
    }
    _write_json(review_dir / "receipt.json", receipt)
    return {"result": "PASS", "required": True, "counts": counts}


def run_verification_gate(
    context: RunContext,
    risk: InfraRiskProfile,
    *,
    pre_changed: list[InfraChangedPath],
    skip_verify: bool,
    timeout_seconds: int,
) -> tuple[dict[str, object], str, str]:
    logs_dir = context.run_dir / "logs" / "verification"
    logs_dir.mkdir(parents=True, exist_ok=True)
    pre_hashes = _content_hashes(context, pre_changed)
    commands = [["python", "scripts/ao.py", "agentic-check"]]
    skipped: list[str] = []
    if risk.requires_runner_tests:
        if skip_verify:
            skipped.append("workflow-runner-tests")
        else:
            commands.append(
                [
                    "uv",
                    "run",
                    "--project",
                    "tools/workflow_runner",
                    "python",
                    "-m",
                    "pytest",
                    "tools/workflow_runner/tests",
                ]
            )
    if risk.requires_entrypoint_smoke and not skip_verify:
        commands.extend(
            [
                ["python", "scripts/ao.py", "--help"],
                ["python", "scripts/ao.py", "workflow", "--help"],
                ["python", "scripts/ao.py", "ao-infra", "--help"],
            ]
        )
    records = []
    sections = []
    for index, command in enumerate(commands, start=1):
        started = time.time()
        result = run_command(command, cwd=context.repo_root, timeout_seconds=timeout_seconds)
        completed = time.time()
        name = _command_name(command, index)
        stdout_path = logs_dir / f"{name}.stdout.txt"
        stderr_path = logs_dir / f"{name}.stderr.txt"
        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")
        records.append(
            {
                "name": name,
                "command": " ".join(command),
                "required": True,
                "exit_code": result.return_code,
                "started_at": started,
                "completed_at": completed,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
        )
        sections.append(f"COMMAND: {' '.join(command)}\n退出码={result.return_code}")
        if result.return_code != 0:
            raise ControlPlaneGateError(f"verification_failed: {name}")
    if risk.high_risk and skip_verify and "high-risk-verification" not in skipped:
        skipped.append("high-risk-verification")
    post_changed = implementation_changed_set(context)
    post_hashes = _content_hashes(context, post_changed)
    modified_by_verification = sorted(
        path
        for path, pre_hash in pre_hashes.items()
        if post_hashes.get(path) != pre_hash and not _is_allowed_verification_delta(context, path)
    )
    if modified_by_verification:
        raise ControlPlaneGateError(
            "unexpected_verification_output: " + ", ".join(modified_by_verification)
        )
    delta = _changed_delta(pre_changed, post_changed)
    unexpected = [item for item in delta if not _is_allowed_verification_delta(context, item.path)]
    if unexpected:
        raise ControlPlaneGateError(
            "unexpected_verification_output: " + ", ".join(item.path for item in unexpected)
        )
    status = STATUS_NEEDS_VERIFICATION if risk.high_risk and skip_verify else STATUS_PASSED
    return (
        {
            "result": "PASS" if status == STATUS_PASSED else status,
            "commands": records,
            "skipped": skipped,
            "pre_verification_changed_set": [item.to_dict() for item in pre_changed],
            "post_verification_changed_set": [item.to_dict() for item in post_changed],
            "verification_delta": [item.to_dict() for item in delta],
        },
        "\n\n".join(sections),
        status,
    )


def _validate_changed_files_artifact(
    context: RunContext,
    computed: list[InfraChangedPath],
) -> None:
    path = context.run_dir / "changed-files.json"
    if not path.exists():
        raise ControlPlaneGateError("missing_required_artifact: changed-files.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, list):
        raise ControlPlaneGateError("invalid_changed_files_json")
    declared = [
        InfraChangedPath(
            path=normalize_path(str(item["path"])),
            status=str(item["status"]),
            old_path=str(item["old_path"]) if item.get("old_path") else None,
        )
        for item in raw_paths
        if isinstance(item, dict) and item.get("path") and item.get("status")
    ]
    computed_set = {item.key() for item in computed}
    declared_set = {item.key() for item in declared}
    if declared_set != computed_set:
        declared_paths = {item.path for item in declared}
        computed_paths = {item.path for item in computed}
        if declared_paths == computed_paths:
            raise ControlPlaneGateError("changed_set_status_mismatch")
        if not declared_set.issuperset(computed_set):
            raise ControlPlaneGateError("changed_set_underreported")
        if not declared_set.issubset(computed_set):
            raise ControlPlaneGateError("changed_set_overreported")
        raise ControlPlaneGateError("changed_set_status_mismatch")


def _validate_forbidden_paths(changed: list[InfraChangedPath]) -> None:
    forbidden = [item.path for item in changed if item.path.startswith("apps/")]
    if forbidden:
        raise ControlPlaneGateError("forbidden_business_app: " + ", ".join(forbidden))


def _status_from_xy(xy: str) -> str:
    if "D" in xy:
        return "deleted"
    if "A" in xy:
        return "added"
    if "M" in xy:
        return "modified"
    return "modified"


def _is_runner_generated_path(context: RunContext, path: str) -> bool:
    prefixes = {
        _relative_prefix(context.repo_root, context.run_dir),
        "output/tmp/ao-infra-smoke-project/",
    }
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in prefixes if prefix)


def _relative_prefix(root: Path, path: Path) -> str:
    try:
        return normalize_path(path.resolve().relative_to(root.resolve())) + "/"
    except ValueError:
        return ""


def _template_path_is_manifested(repo_root: Path, path: str) -> bool:
    manifest = load_manifest(repo_root)
    template_root = normalize_path(manifest["template_root"])
    for prefix in managed_directory_template_prefixes(repo_root):
        if path.startswith(prefix):
            return True
    for entry in iter_managed_files(repo_root, manifest):
        try:
            source = normalize_path(entry.source.resolve().relative_to(repo_root.resolve()))
        except ValueError:
            source = normalize_path(entry.source)
        if source == path:
            return True
    for entry in iter_template_files(repo_root, manifest, "init_only_files"):
        try:
            source = normalize_path(entry.source.resolve().relative_to(repo_root.resolve()))
        except ValueError:
            source = normalize_path(entry.source)
        if source == path:
            return True
    return not path.startswith(template_root + "/")


def _managed_directory_mismatches(repo_root: Path, changed_paths: set[str]) -> list[str]:
    manifest = load_manifest(repo_root)
    lock = read_lock(repo_root)
    template_root = normalize_path(manifest["template_root"]).rstrip("/")
    paths_to_check: set[str] = set()
    for prefix in managed_directory_prefixes(repo_root):
        for path in changed_paths:
            if path.startswith(prefix):
                paths_to_check.add(path)
    for template_prefix in managed_directory_template_prefixes(repo_root):
        for path in changed_paths:
            if path.startswith(template_prefix):
                paths_to_check.add(path[len(template_root) + 1 :])
    mismatches: list[str] = []
    for root_path in sorted(paths_to_check):
        root_file = repo_root / Path(root_path)
        template_file = repo_root / Path(template_root) / Path(root_path)
        if not root_file.exists() or not template_file.exists():
            mismatches.append(root_path)
            continue
        root_hash = sha256_file(root_file)
        template_hash = sha256_file(template_file)
        lock_hash = (lock.get("files", {}).get(root_path) or {}).get("sha256")
        if root_hash != template_hash or root_hash != lock_hash:
            mismatches.append(root_path)
    return mismatches


def _command_name(command: list[str], index: int) -> str:
    if command[:3] == ["python", "scripts/ao.py", "agentic-check"]:
        return "agentic-check"
    if "pytest" in command:
        return "workflow-runner-tests"
    return f"command-{index}"


def _changed_delta(
    before: list[InfraChangedPath],
    after: list[InfraChangedPath],
) -> list[InfraChangedPath]:
    before_set = {item.key() for item in before}
    return [item for item in after if item.key() not in before_set]


def _content_hashes(context: RunContext, changed: list[InfraChangedPath]) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for item in changed:
        if _is_runner_generated_path(context, item.path):
            continue
        path = context.repo_root / Path(item.path)
        if path.exists() and path.is_file():
            hashes[item.path] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            hashes[item.path] = None
    return hashes


def _is_allowed_verification_delta(context: RunContext, path: str) -> bool:
    return _is_runner_generated_path(context, path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
