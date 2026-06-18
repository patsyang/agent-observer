from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from agentic_workflow.models import RunContext

WAITING_STATE_PATTERNS = (
    "请提供",
    "需要你提供",
    "我已就绪",
    "等待输入",
    "无法开始",
    "没有看到具体任务",
)


def missing_required_artifacts(artifacts_dir: Path, required_artifacts: list[str]) -> list[str]:
    missing = []
    for name in required_artifacts:
        path = artifacts_dir / name
        if not path.exists() or (path.is_file() and path.stat().st_size == 0):
            missing.append(name)
    return missing


def effective_node_return_code(
    return_code: int,
    missing: list[str],
    waiting_state: str | None = None,
) -> int:
    if return_code == 0 and waiting_state:
        return 66
    if return_code == 0 and missing:
        return 65
    return return_code


def waiting_state_reason(final_message: str) -> str | None:
    normalized = final_message.strip()
    if not normalized:
        return None
    for pattern in WAITING_STATE_PATTERNS:
        if pattern in normalized:
            return pattern
    return None


def write_adapter_diagnostics(
    node_dir: Path,
    *,
    reason: str,
    final_message_path: Path,
) -> None:
    (node_dir / "adapter-diagnostics.json").write_text(
        json.dumps(
            {
                "result": "FAIL",
                "reason": "waiting_state_final_message",
                "matched_text": reason,
                "final_message_path": str(final_message_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def node_env(
    context: RunContext,
    *,
    node_id: str,
    artifacts_dir: Path,
    worktree_path: Path,
    required_artifacts: list[str],
    extra_env: dict[str, str] | None,
    runtime_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AO_RUN_ID": context.run_id,
            "AO_WORKFLOW": context.definition.name,
            "AO_NODE_ID": node_id,
            "AO_ARTIFACTS_DIR": str(artifacts_dir),
            "AO_RUN_DIR": str(context.run_dir),
            "AO_PROJECT_ROOT": str(context.project_root),
            "AO_EXECUTION_ROOT": str(worktree_path),
            "AO_WORKTREE_PATH": str(worktree_path),
            "AO_REQUIRED_ARTIFACTS": json.dumps(required_artifacts, ensure_ascii=False),
        }
    )
    if extra_env:
        env.update(extra_env)
    if runtime_env:
        env.update(runtime_env)
    return env


def read_final_message(path: Path, return_code: int, *, adapter_label: str) -> str:
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return f"{adapter_label} adapter 已结束，退出码为 {return_code}。"


def changed_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short", "--untracked-files=all"],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip())
    return files
