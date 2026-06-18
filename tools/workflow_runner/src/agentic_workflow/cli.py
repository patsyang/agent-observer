import argparse
import json
from pathlib import Path

from .definitions import list_definitions, validate_definition
from .e2e_runner import cleanup_run, read_run_status, resume_run, run_e2e_workflow
from .features import init_source_package_from_document
from .infra import configure_project_runtime, init_project, plan_update, write_update_plan
from .models import WorkflowInput
from .plan_gates import check_plan_artifact, format_plan_gate_result
from .project_registry import (
    get_project,
    list_projects,
    project_status_payload,
    rebind_project,
    register_project,
    resolve_project_root,
)
from .project_onboarding import (
    NeedsModelSelection,
    models_payload,
    register_project_onboarding,
    stack_profiles_payload,
)
from .quality_gates import check_spec_artifacts, format_gate_result
from .runner import complete_run, create_run_context, execute_run, prepare_run
from .stack_contract import StackContractError, confirm_stack_contract, load_stack_contract


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    if _handle_static_command(args, repo_root):
        return

    context = create_run_context(repo_root, _workflow_input_from_args(args), run_id=args.run_id)
    _run_context_command(args, context)


def _handle_static_command(args: argparse.Namespace, repo_root: Path) -> bool:
    if args.command == "list":
        for definition in list_definitions(repo_root):
            print(f"{definition.name}\t{definition.title}\tadapter={definition.adapter}")
        return True

    if args.command == "validate":
        result = validate_definition(repo_root, args.workflow)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["status"] == "PASS" else 1)

    if args.command == "init-project":
        result = init_project(
            infra_root=repo_root,
            target_root=Path(args.target),
            project_name=args.project_name,
            model_id=args.model,
            force=args.force,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return True

    if args.command == "update-project":
        output_path = _resolve_output_path(repo_root, args.output)
        plan = plan_update(
            project_root=repo_root,
            infra_root=Path(args.infra_root).resolve(),
        )
        write_update_plan(plan, output_path)
        print(json.dumps(plan["summary"], ensure_ascii=False, indent=2))
        print(f"plan={output_path}")
        return True

    if args.command == "project":
        _run_project_command(args, repo_root)
        return True

    if args.command == "init-feature":
        target_root = _resolve_feature_target_root(args, repo_root)
        result = init_source_package_from_document(
            repo_root=repo_root,
            project_name=args.project_name,
            doc_type=args.doc_type,
            source_path=args.source,
            target_root=target_root,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return True

    if args.command == "check-spec":
        result = check_spec_artifacts(
            spec_path=_resolve_output_path(repo_root, args.spec_path),
            plan_path=_resolve_optional_path(repo_root, args.plan_path),
            tasks_path=_resolve_optional_path(repo_root, args.tasks_path),
        )
        print(format_gate_result(result))
        raise SystemExit(0 if result.ok else 1)

    if args.command == "check-plan":
        result = check_plan_artifact(_resolve_output_path(repo_root, args.plan_path))
        print(format_plan_gate_result(result))
        raise SystemExit(0 if result.ok else 1)

    if args.command == "resume":
        result = resume_run(repo_root, args.run_id)
        print(f"run_id={args.run_id}")
        print(f"summary={result.summary}")
        raise SystemExit(result.return_code)

    if args.command == "status":
        status = read_run_status(repo_root, args.run_id)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        raise SystemExit(0)

    if args.command == "cleanup":
        removed = cleanup_run(repo_root, args.run_id, force=args.force)
        print(json.dumps({"run_id": args.run_id, "worktree_removed": removed}, ensure_ascii=False))
        raise SystemExit(0)

    return False


def _resolve_feature_target_root(args: argparse.Namespace, repo_root: Path) -> Path | None:
    if not (args.project or args.project_root):
        return None
    target_root, _ = resolve_project_root(
        control_repo_root=repo_root,
        project=args.project,
        project_root=args.project_root,
    )
    return target_root


def _workflow_input_from_args(args: argparse.Namespace) -> WorkflowInput:
    return WorkflowInput(
        workflow=args.workflow,
        goal=args.goal,
        goal_path=args.goal_path,
        prd_path=args.prd_path,
        source_spec_path=args.source_spec_path,
        spec_path=args.spec_path,
        plan_path=args.plan_path,
        scope=args.scope,
        project=args.project,
        project_root=args.project_root,
    )


def _run_context_command(args: argparse.Namespace, context) -> None:
    if args.command == "prepare":
        run_dir = prepare_run(context)
        print(f"run_id={context.run_id}")
        print(f"run_dir={run_dir}")
        return

    if args.command == "execute":
        return_code = execute_run(
            context,
            adapter_name=args.adapter,
            adapter_command=args.adapter_command,
            adapter_profile=args.adapter_profile,
            skip_verify=args.skip_verify,
            timeout_seconds=args.timeout_seconds,
        )
        raise SystemExit(return_code)

    if args.command == "run":
        prepare_run(context)
        result = run_e2e_workflow(
            context,
            use_worktree=not args.no_worktree,
        )
        complete_code = complete_run(
            context,
            summary=result.summary,
            changed_files=result.changed_files,
            skip_verify=args.skip_verify,
        )
        print(f"run_id={context.run_id}")
        print(f"run_dir={context.run_dir}")
        raise SystemExit(result.return_code or complete_code)

    return_code = complete_run(
        context,
        summary=args.summary,
        changed_files=args.changed_file or [],
        skip_verify=args.skip_verify,
    )
    raise SystemExit(return_code)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-workflow")
    parser.add_argument("--repo-root", default=".")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("list")
    validate = subcommands.add_parser("validate")
    validate.add_argument("--workflow", required=True)
    add_project_parser(subcommands.add_parser("project"))
    init = subcommands.add_parser("init-project")
    init.add_argument("--target", required=True)
    init.add_argument("--project-name", required=True)
    init.add_argument("--model")
    init.add_argument("--force", action="store_true")
    update = subcommands.add_parser("update-project")
    update.add_argument("--infra-root", default=".")
    update.add_argument("--output", default="output/tmp/agentic-update-plan.json")
    init_feature = subcommands.add_parser("init-feature")
    init_feature.add_argument("--project-name", required=True)
    init_feature.add_argument("--doc-type", choices=["prd", "spec"], required=True)
    init_feature.add_argument("--source", required=True)
    init_feature.add_argument("--project")
    init_feature.add_argument("--project-root")
    check_spec = subcommands.add_parser("check-spec")
    check_spec.add_argument("--spec-path", required=True)
    check_spec.add_argument("--plan-path")
    check_spec.add_argument("--tasks-path")
    check_plan = subcommands.add_parser("check-plan")
    check_plan.add_argument("--plan-path", required=True)
    add_run_args(subcommands.add_parser("prepare"))
    run = add_run_args(subcommands.add_parser("run"))
    run.add_argument("--skip-verify", action="store_true")
    run.add_argument("--no-worktree", action="store_true")
    complete = add_run_args(subcommands.add_parser("complete"))
    complete.add_argument("--summary", required=True)
    complete.add_argument("--changed-file", action="append")
    complete.add_argument("--skip-verify", action="store_true")
    execute = add_run_args(subcommands.add_parser("execute"))
    execute.add_argument("--adapter", default="codex")
    execute.add_argument("--adapter-command", action="append")
    execute.add_argument("--adapter-profile")
    execute.add_argument("--timeout-seconds", type=int, default=3600)
    execute.add_argument("--skip-verify", action="store_true")
    resume = subcommands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    status = subcommands.add_parser("status")
    status.add_argument("--run-id", required=True)
    cleanup = subcommands.add_parser("cleanup")
    cleanup.add_argument("--run-id", required=True)
    cleanup.add_argument("--force", action="store_true")
    return parser


def add_run_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--scope")
    parser.add_argument("--project")
    parser.add_argument("--project-root")
    parser.add_argument("--run-id")
    parser.add_argument("--goal")
    parser.add_argument("--goal-path")
    parser.add_argument("--prd-path")
    parser.add_argument("--source-spec-path")
    parser.add_argument("--spec-path")
    parser.add_argument("--plan-path")
    return parser


def add_project_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="project_action", required=True)
    register = actions.add_parser("register")
    register.add_argument("--name", required=True)
    register.add_argument("--root", required=True)
    register.add_argument("--workspace-root")
    register.add_argument("--model")
    register.add_argument("--stack-profile")
    actions.add_parser("models")
    actions.add_parser("list")
    status = actions.add_parser("status")
    status.add_argument("identifier")
    rebind = actions.add_parser("rebind")
    rebind.add_argument("identifier")
    rebind.add_argument("--root", required=True)
    configure = actions.add_parser("configure-runtime")
    configure.add_argument("--project", required=True)
    configure.add_argument("--model", required=True)
    stack = actions.add_parser("stack")
    stack_actions = stack.add_subparsers(dest="stack_action", required=True)
    stack_actions.add_parser("profiles")
    stack_status = stack_actions.add_parser("status")
    stack_status.add_argument("identifier")
    stack_confirm = stack_actions.add_parser("confirm")
    stack_confirm.add_argument("identifier")
    stack_confirm.add_argument("--from", dest="source_path", required=True)


def _run_project_command(args: argparse.Namespace, repo_root: Path) -> None:
    if args.project_action == "register":
        try:
            payload = register_project_onboarding(
                infra_root=repo_root,
                name=args.name,
                root=_resolve_output_path(repo_root, args.root),
                model_id=args.model,
                stack_profile_id=args.stack_profile,
                workspace_root=Path(args.workspace_root) if args.workspace_root else None,
            )
        except NeedsModelSelection as error:
            print(json.dumps(error.payload, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if args.project_action == "models":
        print(json.dumps(models_payload(repo_root), ensure_ascii=False, indent=2))
        return
    if args.project_action == "list":
        print(
            json.dumps(
                [record.to_dict() for record in list_projects()], ensure_ascii=False, indent=2
            )
        )
        return
    if args.project_action == "status":
        try:
            payload, ok = project_status_payload(args.identifier)
        except ValueError:
            raise SystemExit(f"项目未注册: {args.identifier}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not ok:
            raise SystemExit(1)
        return
    if args.project_action == "rebind":
        record = rebind_project(
            identifier=args.identifier,
            root=_resolve_output_path(repo_root, args.root),
        )
        print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        return
    if args.project_action == "configure-runtime":
        record = get_project(args.project)
        if record is None:
            raise SystemExit(f"项目未注册: {args.project}")
        result = configure_project_runtime(
            infra_root=repo_root,
            project_root=record.root_path,
            project_name=record.name,
            model_id=args.model,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.project_action == "stack" and args.stack_action == "profiles":
        print(json.dumps(stack_profiles_payload(repo_root), ensure_ascii=False, indent=2))
        return
    if args.project_action == "stack":
        record = get_project(args.identifier)
        if record is None:
            raise SystemExit(f"项目未注册: {args.identifier}")
        try:
            if args.stack_action == "status":
                contract = load_stack_contract(record.root_path, project_id=record.project_id)
            elif args.stack_action == "confirm":
                contract = confirm_stack_contract(
                    record.root_path,
                    source_path=_resolve_output_path(repo_root, args.source_path),
                    project_id=record.project_id,
                )
            else:
                raise SystemExit(f"unsupported project stack action: {args.stack_action}")
        except StackContractError as error:
            raise SystemExit(str(error))
        print(json.dumps(contract.ref.to_dict(), ensure_ascii=False, indent=2))
        return
    raise SystemExit(f"unsupported project action: {args.project_action}")


def _resolve_output_path(repo_root: Path, output: str) -> Path:
    path = Path(output)
    if path.is_absolute():
        return path
    return repo_root / path


def _resolve_optional_path(repo_root: Path, output: str | None) -> Path | None:
    if not output:
        return None
    return _resolve_output_path(repo_root, output)
