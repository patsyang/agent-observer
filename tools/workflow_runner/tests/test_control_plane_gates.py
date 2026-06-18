import json
import subprocess
from pathlib import Path

import pytest

from agentic_workflow.infra_gates import (
    ControlPlaneGateError,
    InfraChangedPath,
    InfraRiskProfile,
    git_changed_set,
    implementation_changed_set,
    run_verification_gate,
    validate_review_gate,
    validate_template_lock_gate,
)
from agentic_workflow.models import WorkflowInput
from agentic_workflow.runner import complete_run, create_run_context, prepare_run


def test_run_artifacts_are_excluded_but_real_untracked_control_file_is_kept(tmp_path: Path) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_gate",
    )
    prepare_run(context)
    (context.run_dir / "gate-results").mkdir()
    (context.run_dir / "gate-results" / "changed-set.json").write_text("{}", encoding="utf-8")
    (repo / "commands").mkdir()
    (repo / "commands" / "new-command.md").write_text("# new\n", encoding="utf-8")

    changed = implementation_changed_set(context)

    assert [item.path for item in changed] == ["commands/new-command.md"]


def test_control_plane_complete_requires_changed_files_json(tmp_path: Path, monkeypatch) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_missing_changed_json",
    )
    prepare_run(context)
    monkeypatch.setattr(
        "agentic_workflow.infra_gates.run_command",
        lambda *args, **kwargs: _result(0),
    )

    return_code = complete_run(context, summary="done", changed_files=[], skip_verify=True)

    assert return_code == 1
    failure = json.loads((context.run_dir / "gate-results" / "failure.json").read_text())
    assert failure["reason"] == "missing_required_artifact: changed-files.json"


def test_changed_files_json_underreporting_fails(tmp_path: Path, monkeypatch) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_underreported",
    )
    prepare_run(context)
    (repo / "commands").mkdir()
    (repo / "commands" / "ao-infra.md").write_text("# changed\n", encoding="utf-8")
    (context.run_dir / "changed-files.json").write_text(
        json.dumps({"paths": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agentic_workflow.infra_gates.run_command",
        lambda *args, **kwargs: _result(0),
    )

    return_code = complete_run(context, summary="done", changed_files=[], skip_verify=True)

    assert return_code == 1
    failure = json.loads((context.run_dir / "gate-results" / "failure.json").read_text())
    assert failure["reason"] == "changed_set_underreported"


def test_changed_files_json_status_mismatch_fails(tmp_path: Path, monkeypatch) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_status_mismatch",
    )
    prepare_run(context)
    (repo / "commands").mkdir()
    (repo / "commands" / "ao-infra.md").write_text("# changed\n", encoding="utf-8")
    (context.run_dir / "changed-files.json").write_text(
        json.dumps(
            {
                "paths": [
                    {"path": "commands/ao-infra.md", "status": "modified", "old_path": None}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agentic_workflow.infra_gates.run_command",
        lambda *args, **kwargs: _result(0),
    )

    return_code = complete_run(context, summary="done", changed_files=[], skip_verify=True)

    assert return_code == 1
    failure = json.loads((context.run_dir / "gate-results" / "failure.json").read_text())
    assert failure["reason"] == "changed_set_status_mismatch"


def test_review_raw_findings_block_p1(tmp_path: Path) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_review",
    )
    prepare_run(context)
    review_dir = context.run_dir / "review"
    review_dir.mkdir()
    (review_dir / "raw-findings.json").write_text(
        json.dumps(
            {
                "reviewer": {"kind": "sub_agent", "agent_id": "agent-test"},
                "findings": [{"severity": "P1", "reason": "blocking"}],
            }
        ),
        encoding="utf-8",
    )
    (review_dir / "output.md").write_text("P1\n", encoding="utf-8")
    risk = InfraRiskProfile(
        categories=("runner_core",),
        high_risk=True,
        requires_review=True,
        requires_runner_tests=True,
        requires_entrypoint_smoke=False,
        requires_template_lock_gate=False,
    )

    with pytest.raises(ControlPlaneGateError, match="review_has_blocking_findings"):
        validate_review_gate(context, risk)


def test_verification_delta_blocks_unexpected_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_verification_delta",
    )
    prepare_run(context)
    risk = InfraRiskProfile(
        categories=("docs_only",),
        high_risk=False,
        requires_review=False,
        requires_runner_tests=False,
        requires_entrypoint_smoke=False,
        requires_template_lock_gate=False,
    )

    def fake_run_command(*args, **kwargs):
        (repo / "unexpected.txt").write_text("pollution\n", encoding="utf-8")
        return _result(0)

    monkeypatch.setattr("agentic_workflow.infra_gates.run_command", fake_run_command)

    with pytest.raises(ControlPlaneGateError, match="unexpected_verification_output"):
        run_verification_gate(
            context,
            risk,
            pre_changed=[],
            skip_verify=False,
            timeout_seconds=1,
        )


def test_verification_blocks_modifying_existing_changed_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_verification_existing_file",
    )
    prepare_run(context)
    target = repo / "tracked.md"
    target.write_text("before\n", encoding="utf-8")
    _git(repo, "add", "tracked.md")
    _git(repo, "commit", "-m", "tracked")
    target.write_text("changed before verification\n", encoding="utf-8")
    risk = InfraRiskProfile(
        categories=("docs_only",),
        high_risk=False,
        requires_review=False,
        requires_runner_tests=False,
        requires_entrypoint_smoke=False,
        requires_template_lock_gate=False,
    )
    pre_changed = [InfraChangedPath(path="tracked.md", status="modified")]

    def fake_run_command(*args, **kwargs):
        target.write_text("changed by verification\n", encoding="utf-8")
        return _result(0)

    monkeypatch.setattr("agentic_workflow.infra_gates.run_command", fake_run_command)

    with pytest.raises(ControlPlaneGateError, match="unexpected_verification_output"):
        run_verification_gate(
            context,
            risk,
            pre_changed=pre_changed,
            skip_verify=False,
            timeout_seconds=1,
        )


def test_git_status_failure_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ControlPlaneGateError, match="git_status_failed"):
        git_changed_set(tmp_path)


def test_managed_directory_root_template_mismatch_fails(tmp_path: Path, monkeypatch) -> None:
    repo = _control_repo(tmp_path)
    root_file = repo / "tools" / "workflow_runner" / "runner.txt"
    template_file = (
        repo
        / "agentic-infra"
        / "templates"
        / "project"
        / "tools"
        / "workflow_runner"
        / "runner.txt"
    )
    root_file.parent.mkdir(parents=True)
    template_file.parent.mkdir(parents=True)
    root_file.write_text("old\n", encoding="utf-8")
    template_file.write_text("old\n", encoding="utf-8")
    manifest = {
        "infra_name": "test",
        "infra_version": "0.1.0",
        "template_root": "agentic-infra/templates/project",
        "managed_files": [],
        "managed_directories": [{"path": "tools/workflow_runner", "exclude": []}],
        "init_only_files": [],
    }
    (repo / "agentic-infra" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    lock = json.loads((repo / "agentic.lock.json").read_text())
    lock["files"] = {"tools/workflow_runner/runner.txt": {"sha256": _sha256(root_file)}}
    (repo / "agentic.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "managed dir")
    root_file.write_text("new\n", encoding="utf-8")
    lock["files"] = {"tools/workflow_runner/runner.txt": {"sha256": _sha256(root_file)}}
    (repo / "agentic.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_managed_dir_mismatch",
    )
    prepare_run(context)
    (context.run_dir / "changed-files.json").write_text(
        json.dumps(
            {
                "paths": [
                    {
                        "path": "agentic.lock.json",
                        "status": "modified",
                        "old_path": None,
                    },
                    {
                        "path": "tools/workflow_runner/runner.txt",
                        "status": "modified",
                        "old_path": None,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    review_dir = context.run_dir / "review"
    review_dir.mkdir()
    (review_dir / "raw-findings.json").write_text(
        json.dumps({"reviewer": {"kind": "sub_agent", "agent_id": "agent-test"}, "findings": []}),
        encoding="utf-8",
    )
    (review_dir / "output.md").write_text("No blocking findings.\n", encoding="utf-8")
    monkeypatch.setattr(
        "agentic_workflow.infra_gates.run_command",
        lambda *args, **kwargs: _result(0),
    )

    return_code = complete_run(context, summary="done", changed_files=[], skip_verify=True)

    assert return_code == 1
    failure = json.loads((context.run_dir / "gate-results" / "failure.json").read_text())
    assert failure["reason"].startswith("managed_directory_template_lock_mismatch")


def test_managed_directory_template_mirror_can_pass_when_synced(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _managed_directory_repo(tmp_path)
    root_file = repo / "tools" / "workflow_runner" / "runner.txt"
    template_file = (
        repo
        / "agentic-infra"
        / "templates"
        / "project"
        / "tools"
        / "workflow_runner"
        / "runner.txt"
    )
    root_file.write_text("new\n", encoding="utf-8")
    template_file.write_text("new\n", encoding="utf-8")
    lock = json.loads((repo / "agentic.lock.json").read_text())
    lock["files"] = {"tools/workflow_runner/runner.txt": {"sha256": _sha256(root_file)}}
    (repo / "agentic.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_managed_dir_synced",
    )
    prepare_run(context)
    (context.run_dir / "changed-files.json").write_text(
        json.dumps(
            {
                "paths": [
                    {"path": "agentic.lock.json", "status": "modified", "old_path": None},
                    {
                        "path": "agentic-infra/templates/project/tools/workflow_runner/runner.txt",
                        "status": "modified",
                        "old_path": None,
                    },
                    {
                        "path": "tools/workflow_runner/runner.txt",
                        "status": "modified",
                        "old_path": None,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_clean_review(context)
    monkeypatch.setattr(
        "agentic_workflow.infra_gates.run_command",
        lambda *args, **kwargs: _result(0),
    )

    return_code = complete_run(context, summary="done", changed_files=[], skip_verify=True)

    assert return_code == 3
    verification = json.loads((context.run_dir / "gate-results" / "verification.json").read_text())
    assert verification["result"] == "NEEDS_VERIFICATION"
    assert not (context.run_dir / "gate-results" / "failure.json").exists()


def test_template_lock_gate_allows_deleted_unmanifested_template_file(tmp_path: Path) -> None:
    repo = _control_repo(tmp_path)
    stale = repo / "agentic-infra" / "templates" / "project" / ".agentic" / "spec-templates" / "spec.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# stale\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "stale template")
    stale.unlink()
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_deleted_template",
    )
    prepare_run(context)
    risk = InfraRiskProfile(
        categories=("infra_template",),
        high_risk=True,
        requires_review=True,
        requires_runner_tests=False,
        requires_entrypoint_smoke=False,
        requires_template_lock_gate=True,
    )

    result = validate_template_lock_gate(
        context,
        [
            InfraChangedPath(
                path="agentic-infra/templates/project/.agentic/spec-templates/spec.md",
                status="deleted",
            )
        ],
        risk,
    )

    assert result["result"] == "PASS"


def test_template_lock_gate_allows_changed_init_only_template(tmp_path: Path) -> None:
    repo = _control_repo(tmp_path)
    readme = repo / "agentic-infra" / "templates" / "project" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("# Project\n", encoding="utf-8")
    manifest = json.loads((repo / "agentic-infra" / "manifest.json").read_text())
    manifest["init_only_files"] = [{"path": "README.md"}]
    (repo / "agentic-infra" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init only readme")
    readme.write_text("# Project\n\nUpdated.\n", encoding="utf-8")
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_init_only_template",
    )
    prepare_run(context)
    risk = InfraRiskProfile(
        categories=("infra_template",),
        high_risk=True,
        requires_review=True,
        requires_runner_tests=False,
        requires_entrypoint_smoke=False,
        requires_template_lock_gate=True,
    )

    result = validate_template_lock_gate(
        context,
        [InfraChangedPath(path="agentic-infra/templates/project/README.md", status="modified")],
        risk,
    )

    assert result["result"] == "PASS"


def test_managed_directory_template_mirror_mismatch_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _managed_directory_repo(tmp_path)
    template_file = (
        repo
        / "agentic-infra"
        / "templates"
        / "project"
        / "tools"
        / "workflow_runner"
        / "runner.txt"
    )
    template_file.write_text("template only\n", encoding="utf-8")
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_managed_dir_template_mismatch",
    )
    prepare_run(context)
    (context.run_dir / "changed-files.json").write_text(
        json.dumps(
            {
                "paths": [
                    {
                        "path": "agentic-infra/templates/project/tools/workflow_runner/runner.txt",
                        "status": "modified",
                        "old_path": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_clean_review(context)
    monkeypatch.setattr(
        "agentic_workflow.infra_gates.run_command",
        lambda *args, **kwargs: _result(0),
    )

    return_code = complete_run(context, summary="done", changed_files=[], skip_verify=True)

    assert return_code == 1
    failure = json.loads((context.run_dir / "gate-results" / "failure.json").read_text())
    assert failure["reason"].startswith("managed_directory_template_lock_mismatch")


def test_review_rejects_invalid_p2_disposition(tmp_path: Path) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_review_p2",
    )
    prepare_run(context)
    review_dir = context.run_dir / "review"
    review_dir.mkdir()
    (review_dir / "raw-findings.json").write_text(
        json.dumps(
            {
                "reviewer": {"kind": "sub_agent", "agent_id": "agent-test"},
                "findings": [{"severity": "P2", "reason": "minor", "disposition": "ignored"}],
            }
        ),
        encoding="utf-8",
    )
    (review_dir / "output.md").write_text("P2 minor\n", encoding="utf-8")
    risk = InfraRiskProfile(
        categories=("runner_core",),
        high_risk=True,
        requires_review=True,
        requires_runner_tests=True,
        requires_entrypoint_smoke=False,
        requires_template_lock_gate=False,
    )

    with pytest.raises(ControlPlaneGateError, match="review_has_unhandled_p2"):
        validate_review_gate(context, risk)


@pytest.mark.parametrize(
    "reviewer",
    [
        None,
        {"kind": "human", "agent_id": "agent-test"},
        {"kind": "sub_agent", "agent_id": ""},
    ],
)
def test_review_rejects_invalid_reviewer_receipt(tmp_path: Path, reviewer: object) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_review_receipt",
    )
    prepare_run(context)
    review_dir = context.run_dir / "review"
    review_dir.mkdir()
    payload = {"findings": []}
    if reviewer is not None:
        payload["reviewer"] = reviewer
    (review_dir / "raw-findings.json").write_text(json.dumps(payload), encoding="utf-8")
    (review_dir / "output.md").write_text("No blocking findings.\n", encoding="utf-8")
    risk = InfraRiskProfile(
        categories=("runner_core",),
        high_risk=True,
        requires_review=True,
        requires_runner_tests=True,
        requires_entrypoint_smoke=False,
        requires_template_lock_gate=False,
    )

    with pytest.raises(ControlPlaneGateError, match="invalid_review_receipt"):
        validate_review_gate(context, risk)


def test_high_risk_skip_verify_needs_verification(tmp_path: Path, monkeypatch) -> None:
    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_skip_verify",
    )
    prepare_run(context)
    (repo / ".agentic" / "workflow" / "definitions" / "control-plane-change.json").write_text(
        json.dumps(
            {
                "name": "control-plane-change",
                "title": "changed",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/control-plane-change.md",
                "primary_inputs": ["goal", "goal_path"],
                "stages": ["scope-check", "implementation"],
                "verify_policy": "control-plane",
            }
        ),
        encoding="utf-8",
    )
    (context.run_dir / "changed-files.json").write_text(
        json.dumps(
            {
                "paths": [
                    {
                        "path": ".agentic/workflow/definitions/control-plane-change.json",
                        "status": "modified",
                        "old_path": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    review_dir = context.run_dir / "review"
    review_dir.mkdir()
    (review_dir / "raw-findings.json").write_text(
        json.dumps({"reviewer": {"kind": "sub_agent", "agent_id": "agent-test"}, "findings": []}),
        encoding="utf-8",
    )
    (review_dir / "output.md").write_text("No blocking findings.\n", encoding="utf-8")
    monkeypatch.setattr(
        "agentic_workflow.infra_gates.run_command",
        lambda *args, **kwargs: _result(0),
    )

    return_code = complete_run(context, summary="done", changed_files=[], skip_verify=True)

    assert return_code == 3
    state = json.loads((context.run_dir / "run.json").read_text())
    assert state["status"] == "NEEDS_VERIFICATION"


def test_control_plane_resume_invokes_completion_finalizer(tmp_path: Path, monkeypatch) -> None:
    from agentic_workflow.e2e_runner import resume_run

    repo = _control_repo(tmp_path)
    context = create_run_context(
        repo,
        WorkflowInput(workflow="control-plane-change", goal="gate"),
        run_id="run_resume_control",
    )
    prepare_run(context)
    called = {}

    def fake_complete_run(context, summary, changed_files, skip_verify):
        called["run_id"] = context.run_id
        called["skip_verify"] = skip_verify
        return 7

    monkeypatch.setattr("agentic_workflow.runner.complete_run", fake_complete_run)

    result = resume_run(repo, "run_resume_control")

    assert result.return_code == 7
    assert called == {"run_id": "run_resume_control", "skip_verify": False}


def _control_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("/ai_docs/\n/output/\n", encoding="utf-8")
    definition_dir = repo / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / "control-plane-change.json").write_text(
        json.dumps(
            {
                "name": "control-plane-change",
                "title": "control",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/control-plane-change.md",
                "primary_inputs": ["goal", "goal_path"],
                "stages": ["scope-check", "implementation"],
                "verify_policy": "control-plane",
            }
        ),
        encoding="utf-8",
    )
    (repo / ".agentic" / "workflow" / "control-plane-change.md").write_text(
        "# control\n",
        encoding="utf-8",
    )
    (repo / "agentic-infra").mkdir()
    (repo / "agentic-infra" / "manifest.json").write_text(
        json.dumps(
            {
                "infra_name": "test",
                "infra_version": "0.1.0",
                "template_root": "agentic-infra/templates/project",
                "managed_files": [],
                "managed_directories": [],
                "init_only_files": [],
            }
        ),
        encoding="utf-8",
    )
    (repo / "agentic.lock.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "infra_name": "test",
                "infra_version": "0.1.0",
                "project_name": "repo",
                "variables": {},
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def _managed_directory_repo(tmp_path: Path) -> Path:
    repo = _control_repo(tmp_path)
    root_file = repo / "tools" / "workflow_runner" / "runner.txt"
    template_file = (
        repo
        / "agentic-infra"
        / "templates"
        / "project"
        / "tools"
        / "workflow_runner"
        / "runner.txt"
    )
    root_file.parent.mkdir(parents=True)
    template_file.parent.mkdir(parents=True)
    root_file.write_text("old\n", encoding="utf-8")
    template_file.write_text("old\n", encoding="utf-8")
    manifest = {
        "infra_name": "test",
        "infra_version": "0.1.0",
        "template_root": "agentic-infra/templates/project",
        "managed_files": [],
        "managed_directories": [{"path": "tools/workflow_runner", "exclude": []}],
        "init_only_files": [],
    }
    (repo / "agentic-infra" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    lock = json.loads((repo / "agentic.lock.json").read_text())
    lock["files"] = {"tools/workflow_runner/runner.txt": {"sha256": _sha256(root_file)}}
    (repo / "agentic.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "managed dir")
    return repo


def _write_clean_review(context) -> None:
    review_dir = context.run_dir / "review"
    review_dir.mkdir()
    (review_dir / "raw-findings.json").write_text(
        json.dumps({"reviewer": {"kind": "sub_agent", "agent_id": "agent-test"}, "findings": []}),
        encoding="utf-8",
    )
    (review_dir / "output.md").write_text("No blocking findings.\n", encoding="utf-8")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def _result(return_code: int):
    return type("Result", (), {"return_code": return_code, "stdout": "ok", "stderr": ""})()


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
