from __future__ import annotations

import argparse

PROJECT_COMMANDS = {
    "setup",
    "lint",
    "test",
    "e2e",
    "verify",
    "package-collector",
    "dev",
    "stop-dev",
    "status-dev",
}


def build_parser(default_output: str, repo_root: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ao.py")
    subcommands = parser.add_subparsers(dest="command", required=True)
    _add_workflow_parser(subcommands.add_parser("workflow"))
    for name in ("small-change", "plan-execute", "ao-infra"):
        _add_alias_parser(subcommands.add_parser(name))
    _add_spec_parser(subcommands.add_parser("spec-driven"))
    _add_codex_parser(subcommands.add_parser("codex-adapter"))
    _add_cli_adapter_parser(subcommands.add_parser("cli-adapter"))
    _add_project_parser(subcommands.add_parser("project"))
    _add_infra_parsers(subcommands, default_output, repo_root)
    for name in sorted(PROJECT_COMMANDS):
        subcommands.add_parser(name)
    return parser


def _add_workflow_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    validate = actions.add_parser("validate")
    validate.add_argument("--workflow", required=True)
    _add_run_args(actions.add_parser("prepare"))
    run = _add_run_args(actions.add_parser("run"))
    run.add_argument("--skip-verify", action="store_true")
    run.add_argument("--no-worktree", action="store_true")
    complete = _add_run_args(actions.add_parser("complete"))
    _add_complete_parser_args(complete)
    execute = _add_run_args(actions.add_parser("execute"))
    execute.add_argument("--adapter", default="codex")
    execute.add_argument("--adapter-command", action="append")
    execute.add_argument("--adapter-profile")
    execute.add_argument("--timeout-seconds", type=int, default=3600)
    execute.add_argument("--skip-verify", action="store_true")
    resume = actions.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    status = actions.add_parser("status")
    status.add_argument("--run-id", required=True)
    cleanup = actions.add_parser("cleanup")
    cleanup.add_argument("--run-id", required=True)
    cleanup.add_argument("--force", action="store_true")


def _add_alias_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    _add_run_args(actions.add_parser("prepare"), require_workflow=False)
    run = _add_run_args(actions.add_parser("run"), require_workflow=False)
    run.add_argument("--skip-verify", action="store_true")
    run.add_argument("--no-worktree", action="store_true")
    complete = _add_run_args(actions.add_parser("complete"), require_workflow=False)
    _add_complete_parser_args(complete)
    resume = actions.add_parser("resume")
    resume.add_argument("--run-id", required=True)


def _add_spec_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = _add_run_args(actions.add_parser("prepare"), require_workflow=False)
    prepare.add_argument("--project-name")
    prepare.add_argument("--prd")
    prepare.add_argument("--spec")
    run = _add_run_args(actions.add_parser("run"), require_workflow=False)
    run.add_argument("--project-name")
    run.add_argument("--prd")
    run.add_argument("--spec")
    run.add_argument("--skip-verify", action="store_true")
    run.add_argument("--no-worktree", action="store_true")
    complete = _add_run_args(actions.add_parser("complete"), require_workflow=False)
    _add_complete_parser_args(complete)
    resume = actions.add_parser("resume")
    resume.add_argument("--run-id", required=True)


def _add_codex_parser(parser: argparse.ArgumentParser) -> None:
    _add_run_args(parser)
    parser.add_argument("--codex-executable", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--skip-verify", action="store_true")


def _add_cli_adapter_parser(parser: argparse.ArgumentParser) -> None:
    _add_run_args(parser)
    parser.add_argument("--runtime-executable", required=True)
    parser.add_argument("--runtime-profile", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--skip-verify", action="store_true")


def _add_project_parser(parser: argparse.ArgumentParser) -> None:
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


def _add_infra_parsers(
    subcommands: argparse._SubParsersAction,
    default_output: str,
    repo_root: str,
) -> None:
    check = subcommands.add_parser("agentic-check")
    check.add_argument("--project-root", default=repo_root)
    check.add_argument("--infra-root", default=repo_root)
    check.add_argument("--output", default=default_output)
    update = subcommands.add_parser("agentic-update")
    update.add_argument("--project-root", default=repo_root)
    update.add_argument("--infra-root", default=repo_root)
    update.add_argument("--output", default="output/tmp/agentic-update-plan.json")
    init = subcommands.add_parser("agentic-init-project")
    init.add_argument("--target", required=True)
    init.add_argument("--project-name", required=True)
    init.add_argument("--model")
    init.add_argument("--force", action="store_true")
    plan_check = subcommands.add_parser("plan-check")
    plan_check.add_argument("--plan-path", required=True)
    spec_check = subcommands.add_parser("spec-check")
    spec_check.add_argument("--spec-path", required=True)
    spec_check.add_argument("--plan-path")
    spec_check.add_argument("--tasks-path")


def _add_run_args(
    parser: argparse.ArgumentParser,
    require_workflow: bool = False,
) -> argparse.ArgumentParser:
    parser.add_argument("--workflow", required=require_workflow)
    parser.add_argument("--scope")
    parser.add_argument("--project")
    parser.add_argument("--project-root")
    for name in (
        "run-id",
        "goal",
        "goal-path",
        "prd-path",
        "source-spec-path",
        "spec-path",
        "plan-path",
    ):
        parser.add_argument(f"--{name}")
    return parser


def _add_complete_parser_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--summary")
    parser.add_argument("--summary-file")
    parser.add_argument("--changed-file", action="append")
    parser.add_argument("--changed-files-file")
    parser.add_argument("--skip-verify", action="store_true")
