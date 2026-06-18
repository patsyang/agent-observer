import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> CommandResult:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    try:
        stdout, stderr = process.communicate(input=stdin, timeout=timeout_seconds)
        return CommandResult(process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        terminate_process_tree(process.pid)
        stdout, stderr = process.communicate()
        message = f"命令执行超过 {timeout_seconds}s，已超时"
        return CommandResult(124, stdout, f"{stderr}\n{message}")


def terminate_process_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    process = subprocess.run(["kill", "-TERM", str(pid)], check=False)
    if process.returncode != 0:
        subprocess.run(["kill", "-KILL", str(pid)], check=False)
