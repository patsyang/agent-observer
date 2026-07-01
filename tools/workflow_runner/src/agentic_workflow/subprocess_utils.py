import subprocess
import sys
import threading
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
    # 不能用 communicate(input=stdin, timeout=...)：当子进程不读取 stdin 时，
    # communicate 内部的 stdin 写入会阻塞且不受 timeout 保护，导致整体 timeout 失效。
    # 也不能用 communicate(timeout=...) + 单独线程写 stdin：communicate 会 close stdin，
    # 与写线程争抢 TextIOWrapper 锁导致死锁。
    # 改用三组 daemon 线程分别写 stdin / 读 stdout / 读 stderr，主线程用 wait(timeout) 等进程退出。
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_thread = _start_reader(process.stdout, stdout_chunks)
    stderr_thread = _start_reader(process.stderr, stderr_chunks)
    stdin_thread = _start_stdin_writer(process, stdin)
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_process_tree(process.pid)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    _join_stdin_writer(stdin_thread)
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    if timed_out:
        message = f"命令执行超过 {timeout_seconds}s，已超时"
        return CommandResult(124, stdout, f"{stderr}\n{message}" if stderr else message)
    return CommandResult(process.returncode, stdout, stderr)


def _start_reader(stream, sink: list[str]) -> threading.Thread:
    def _read() -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                sink.append(chunk)
        except (OSError, ValueError):
            pass

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    return thread


def _start_stdin_writer(process: subprocess.Popen, stdin: str | None) -> threading.Thread | None:
    if stdin is None or process.stdin is None:
        return None

    def _write() -> None:
        try:
            process.stdin.write(stdin)
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    thread = threading.Thread(target=_write, daemon=True)
    thread.start()
    return thread


def _join_stdin_writer(thread: threading.Thread | None) -> None:
    if thread is None:
        return
    thread.join(timeout=2)


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
