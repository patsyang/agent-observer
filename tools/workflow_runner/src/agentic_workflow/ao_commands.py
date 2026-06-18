from __future__ import annotations

import argparse

WORKFLOW_BY_ALIAS = {
    "small-change": "small-change",
    "plan-execute": "plan-execute",
    "spec-driven": "spec-driven",
    "ao-infra": "control-plane-change",
}


def build_workflow_args(args: argparse.Namespace, read_summary, read_changed_files) -> list[str]:
    if args.action == "list":
        return ["list"]
    command = [args.action]
    append_run_args(command, args)
    if args.action == "cleanup" and getattr(args, "force", False):
        command.append("--force")
    if args.action == "run":
        append_run_execution_args(command, args)
    if args.action == "complete":
        append_complete_args(command, args, read_summary, read_changed_files)
    if args.action == "execute":
        append_optional(command, "--adapter", args.adapter)
        for item in args.adapter_command or []:
            command += ["--adapter-command", item]
        append_optional(command, "--adapter-profile", args.adapter_profile)
        command += ["--timeout-seconds", str(args.timeout_seconds)]
        if args.skip_verify:
            command.append("--skip-verify")
    return command


def build_alias_args(
    alias: str,
    args: argparse.Namespace,
    read_summary,
    read_changed_files,
) -> list[str]:
    command = [args.action, "--workflow", WORKFLOW_BY_ALIAS[alias]]
    append_run_args(command, args)
    if args.action == "run":
        append_run_execution_args(command, args)
    if args.action == "complete":
        append_complete_args(command, args, read_summary, read_changed_files)
    return command


def build_codex_adapter_args(args: argparse.Namespace) -> list[str]:
    command = ["execute", "--adapter", "codex", "--adapter-command", args.codex_executable]
    append_run_args(command, args)
    command += ["--timeout-seconds", str(args.timeout_seconds)]
    if args.skip_verify:
        command.append("--skip-verify")
    return command


def build_cli_adapter_args(args: argparse.Namespace) -> list[str]:
    command = [
        "execute",
        "--adapter",
        "generic-cli",
        "--adapter-command",
        args.runtime_executable,
        "--adapter-profile",
        args.runtime_profile,
    ]
    append_run_args(command, args)
    command += ["--timeout-seconds", str(args.timeout_seconds)]
    if args.skip_verify:
        command.append("--skip-verify")
    return command


def build_update_args(args: argparse.Namespace) -> list[str]:
    return [
        "--repo-root",
        str(args.project_root_path),
        "update-project",
        "--infra-root",
        str(args.infra_root_path),
        "--output",
        args.output,
    ]


def build_init_project_args(args: argparse.Namespace) -> list[str]:
    command = ["init-project", "--target", args.target, "--project-name", args.project_name]
    append_optional(command, "--model", args.model)
    if args.force:
        command.append("--force")
    return command


def append_run_args(command: list[str], args: argparse.Namespace) -> None:
    for flag, value in (
        ("--workflow", getattr(args, "workflow", None)),
        ("--scope", getattr(args, "scope", None)),
        ("--project", getattr(args, "project", None)),
        ("--project-root", getattr(args, "project_root", None)),
        ("--run-id", getattr(args, "run_id", None)),
        ("--goal", getattr(args, "goal", None)),
        ("--goal-path", getattr(args, "goal_path", None)),
        ("--prd-path", getattr(args, "prd_path", None)),
        ("--source-spec-path", getattr(args, "source_spec_path", None)),
        ("--spec-path", getattr(args, "spec_path", None)),
        ("--plan-path", getattr(args, "plan_path", None)),
    ):
        append_optional(command, flag, value)


def append_optional(command: list[str], flag: str, value: str | None) -> None:
    if value:
        command += [flag, value]


def append_complete_args(command: list[str], args, read_summary, read_changed_files) -> None:
    command += ["--summary", read_summary(args)]
    for path in read_changed_files(args):
        command += ["--changed-file", path]
    if args.skip_verify:
        command.append("--skip-verify")


def append_run_execution_args(command: list[str], args) -> None:
    if getattr(args, "skip_verify", False):
        command.append("--skip-verify")
    if getattr(args, "no_worktree", False):
        command.append("--no-worktree")
