import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


# 轮询间隔：在此间隔内检查进程是否退出，同时检测管道是否已关闭。
# 借鉴 sw-factory BaseCliProvider.HEARTBEAT_INTERVAL_SECONDS=30，缩短为 10s 以更快响应挂死。
PROCESS_POLL_INTERVAL_SECONDS = 10

# 管道关闭后给进程退出的宽限期。stdout/stderr 已 EOF 但进程未退出时
# （如 claude.exe 写完结果后挂死），等待此宽限期后强杀。
# 借鉴 sw-factory BaseCliProvider._wait_for_process 方案二：管道关闭检测。
PIPE_CLOSED_GRACE_SECONDS = 10


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
    pipe_closed_dangling = False
    deadline = time.monotonic() + timeout_seconds

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        poll_interval = min(PROCESS_POLL_INTERVAL_SECONDS, remaining)
        try:
            process.wait(timeout=poll_interval)
            break  # 进程正常退出
        except subprocess.TimeoutExpired:
            # 借鉴 sw-factory 方案二：管道关闭检测
            # stdout/stderr reader 线程均已结束（EOF）但进程未退出，
            # 说明子进程已写完输出但拒不退出（claude.exe 已知行为：写出
            # terminal_reason=completed 的结果 JSON 后进程挂死）。
            # 给短宽限期，仍不退出则强杀并返回已捕获的输出。
            if not stdout_thread.is_alive() and not stderr_thread.is_alive():
                try:
                    process.wait(timeout=PIPE_CLOSED_GRACE_SECONDS)
                    break  # 进程在宽限期内退出
                except subprocess.TimeoutExpired:
                    pipe_closed_dangling = True
                    break

    if timed_out or pipe_closed_dangling:
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
    if pipe_closed_dangling:
        # 管道已关闭（输出完整捕获），但进程未自行退出，已强杀。
        # 返回 0 让调用方通过 payload 校验决定真实成功/失败
        # （generic_cli._return_code_for_profile 会检查 stdout JSON 的 success_json_conditions）。
        message = (
            f"子进程 stdout/stderr 已关闭但未自行退出"
            f"（等待 {PIPE_CLOSED_GRACE_SECONDS}s 后强杀）；"
            "输出已完整捕获，由调用方校验 payload 决定成败"
        )
        return CommandResult(0, stdout, f"{stderr}\n{message}" if stderr else message)
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
