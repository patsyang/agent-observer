from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .ao_commands import (
    build_alias_args as _build_alias_args,
)
from .ao_commands import (
    build_codex_adapter_args,
    build_cli_adapter_args,
    build_init_project_args,
)
from .ao_commands import (
    build_update_args as _build_update_args,
)
from .ao_commands import (
    build_workflow_args as _build_workflow_args,
)
from .ao_parser import PROJECT_COMMANDS, build_parser
from .infra import configure_project_runtime
from .project_onboarding import (
    NeedsModelSelection,
    models_payload,
    register_project_onboarding,
    stack_profiles_payload,
)
from .project_commands import run_project_command
from .project_registry import (
    get_project,
    list_projects,
    project_status_payload,
    rebind_project,
    register_project,
)
from .stack_contract import StackContractError, confirm_stack_contract, load_stack_contract

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = "output/tmp/agentic-check-plan.json"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(DEFAULT_OUTPUT, str(REPO_ROOT))
    return dispatch(parser.parse_args(argv))


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "workflow":
        return run_agentic(build_workflow_args(args))
    if args.command in {"small-change", "plan-execute", "ao-infra"}:
        return run_agentic(build_alias_args(args.command, args))
    if args.command == "spec-driven":
        return run_agentic(build_spec_driven_args(args))
    if args.command == "codex-adapter":
        return run_agentic(build_codex_adapter_args(args))
    if args.command == "cli-adapter":
        return run_agentic(build_cli_adapter_args(args))
    if args.command == "project":
        return run_project_registry_command(args)
    if args.command == "agentic-check":
        return run_agentic_check(args)
    if args.command == "agentic-update":
        return run_agentic(build_update_args(args))
    if args.command == "agentic-init-project":
        return run_agentic(build_init_project_args(args))
    if args.command == "plan-check":
        return run_agentic(["check-plan", "--plan-path", args.plan_path])
    if args.command == "spec-check":
        command = ["check-spec", "--spec-path", args.spec_path]
        _append_optional(command, "--plan-path", args.plan_path)
        _append_optional(command, "--tasks-path", args.tasks_path)
        return run_agentic(command)
    if args.command in PROJECT_COMMANDS:
        return run_project_command(REPO_ROOT, args.command)
    raise ValueError(f"unsupported command: {args.command}")


def run_project_registry_command(args: argparse.Namespace) -> int:
    if args.project_action == "register":
        try:
            payload = register_project_onboarding(
                infra_root=REPO_ROOT,
                name=args.name,
                root=_resolve_repo_path(args.root),
                model_id=args.model,
                stack_profile_id=args.stack_profile,
                workspace_root=Path(args.workspace_root) if args.workspace_root else None,
            )
        except NeedsModelSelection as error:
            print(json.dumps(error.payload, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.project_action == "models":
        print(json.dumps(models_payload(REPO_ROOT), ensure_ascii=False, indent=2))
        return 0
    if args.project_action == "list":
        print(
            json.dumps(
                [record.to_dict() for record in list_projects()], ensure_ascii=False, indent=2
            )
        )
        return 0
    if args.project_action == "status":
        try:
            payload, ok = project_status_payload(args.identifier)
        except ValueError:
            print(f"项目未注册: {args.identifier}", file=sys.stderr)
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    if args.project_action == "rebind":
        record = rebind_project(identifier=args.identifier, root=_resolve_repo_path(args.root))
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.project_action == "configure-runtime":
        record = get_project(args.project)
        if record is None:
            print(f"项目未注册: {args.project}", file=sys.stderr)
            return 1
        result = configure_project_runtime(
            infra_root=REPO_ROOT,
            project_root=record.root_path,
            project_name=record.name,
            model_id=args.model,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.project_action == "stack":
        return run_project_stack_command(args)
    raise ValueError(f"unsupported project action: {args.project_action}")


def run_project_stack_command(args: argparse.Namespace) -> int:
    if args.stack_action == "profiles":
        print(json.dumps(stack_profiles_payload(REPO_ROOT), ensure_ascii=False, indent=2))
        return 0
    record = get_project(args.identifier)
    if record is None:
        print(f"项目未注册: {args.identifier}", file=sys.stderr)
        return 1
    try:
        if args.stack_action == "status":
            contract = load_stack_contract(record.root_path, project_id=record.project_id)
        elif args.stack_action == "confirm":
            contract = confirm_stack_contract(
                record.root_path,
                source_path=_resolve_repo_path(args.source_path),
                project_id=record.project_id,
            )
        else:
            raise ValueError(f"unsupported stack action: {args.stack_action}")
    except StackContractError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(contract.ref.to_dict(), ensure_ascii=False, indent=2))
    return 0


def build_workflow_args(args: argparse.Namespace) -> list[str]:
    return _build_workflow_args(args, _read_summary, _read_changed_files)


def build_alias_args(alias: str, args: argparse.Namespace) -> list[str]:
    return _build_alias_args(alias, args, _read_summary, _read_changed_files)


def build_spec_driven_args(args: argparse.Namespace) -> list[str]:
    if args.action == "resume":
        return ["resume", "--run-id", args.run_id]
    if args.action == "complete":
        return build_alias_args("spec-driven", args)
    _validate_spec_driven_start_args(args)
    if (
        args.project_name
        and not getattr(args, "project", None)
        and not getattr(args, "project_root", None)
    ):
        args.project = args.project_name
    if args.prd:
        args.prd_path = args.prd
    if args.spec:
        args.source_spec_path = args.spec
    args.workflow = "spec-driven"
    if args.action == "prepare":
        args.action = "prepare"
    return build_workflow_args(args)


def build_update_args(args: argparse.Namespace) -> list[str]:
    args.project_root_path = Path(args.project_root).resolve()
    args.infra_root_path = Path(args.infra_root).resolve()
    return _build_update_args(args)


def run_agentic_check(args: argparse.Namespace) -> int:
    result = run_agentic_capture(build_update_args(args))
    sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode != 0:
        return result.returncode
    plan_path = _resolve_against(Path(args.project_root).resolve(), args.output)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    drifted = [item for item in plan["items"] if item["status"] != "unchanged"]
    if drifted:
        for item in drifted:
            fields = (
                item["path"],
                item["status"],
                item.get("current_sha256"),
                item.get("baseline_sha256"),
                item.get("infra_sha256"),
            )
            print("\t".join(str(field) for field in fields))
        print(
            f"agentic infra drift detected: {len(drifted)} files are not unchanged.",
            file=sys.stderr,
        )
        return 1
    print("agentic infra drift check passed.")
    return 0


def run_agentic(command_args: list[str]) -> int:
    if command_args == ["__failed__"]:
        return 1
    result = run_agentic_capture(command_args)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


def run_agentic_capture(command_args: list[str]) -> subprocess.CompletedProcess[str]:
    base_args = ["uv", "run", "--project", "tools/workflow_runner", "agentic-workflow"]
    if command_args and command_args[0] == "--repo-root":
        args = base_args + command_args
    else:
        args = base_args + ["--repo-root", str(REPO_ROOT), *command_args]
    return subprocess.run(args, cwd=REPO_ROOT, text=True, capture_output=True)


def _append_optional(command: list[str], flag: str, value: str | None) -> None:
    if value:
        command += [flag, value]


def _validate_spec_driven_start_args(args: argparse.Namespace) -> None:
    if args.action not in {"prepare", "run"}:
        return
    selected = [
        name
        for name in ("prd", "spec", "spec_path", "plan_path")
        if getattr(args, name, None)
    ]
    if len(selected) != 1:
        raise SystemExit("provide exactly one of --prd, --spec, --spec-path, or --plan-path")
    if args.prd or args.spec:
        if not getattr(args, "project_name", None):
            raise SystemExit("--project-name is required with --prd or --spec")
        return
    if not (
        getattr(args, "project_name", None)
        or getattr(args, "project", None)
    ):
        raise SystemExit("--project-name or --project is required with --plan-path")


def _read_summary(args: argparse.Namespace) -> str:
    if args.summary and args.summary_file:
        raise SystemExit("provide only one of --summary or --summary-file")
    if args.summary_file:
        return _resolve_repo_path(args.summary_file).read_text(encoding="utf-8").strip()
    if args.summary:
        return args.summary
    raise SystemExit("--summary or --summary-file is required")


def _read_changed_files(args: argparse.Namespace) -> list[str]:
    files = []
    for item in args.changed_file or []:
        files.extend(part.strip() for part in item.split(",") if part.strip())
    if args.changed_files_file:
        lines = _resolve_repo_path(args.changed_files_file).read_text(encoding="utf-8").splitlines()
        files.extend(line.strip() for line in lines if line.strip())
    return files


def _resolve_repo_path(path: str) -> Path:
    return _resolve_against(REPO_ROOT, path)


def _resolve_against(root: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate
