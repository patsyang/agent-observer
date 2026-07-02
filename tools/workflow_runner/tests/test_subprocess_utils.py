"""Tests for subprocess_utils.run_command.

重点验证 pipe-closed-dangling 场景：子进程写完输出并关闭 stdout/stderr 管道后
拒不退出（claude.exe 已知行为）。借鉴 sw-factory BaseCliProvider._wait_for_process
的"方案二：管道关闭检测"——stdout/stderr 已 EOF 但进程未退出时，给宽限期后强杀，
返回已捕获的输出。

回归来源：run_1a8e552f6972 fix-warnings-loop iteration 1，claude.exe 在 23:42:16
写出 terminal_reason=completed 的完整结果 JSON 后，PID 42964 持续 7+ 分钟未退出，
导致 process.wait(timeout=2400) 阻塞，workflow 整体卡死。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from agentic_workflow import subprocess_utils
from agentic_workflow.subprocess_utils import run_command


class _FakePipeStream:
    """模拟 subprocess.PIPE 流，read 在数据耗尽后返回 ''（EOF）。

    run_command 的 reader 线程用 stream.read(4096) 阻塞读取；
    真实 EOF 时 read 返回 ''，reader 线程退出，is_alive()=False。
    """

    def __init__(self, payload: str = "") -> None:
        self._payload = payload
        self._consumed = False

    def read(self, size: int = -1) -> str:
        if self._consumed:
            return ""
        self._consumed = True
        return self._payload


class _FakePopen:
    """模拟 subprocess.Popen 在 pipe-closed-dangling 场景下的行为。

    - stdout/stderr 流的 read() 第一次返回 payload，第二次返回 ''（EOF）
    - wait() 永远 raise TimeoutExpired（模拟进程挂死）

    借鉴 sw-factory tests/test_providers.py 的 FakeProcess
    （test_provider_kills_process_when_pipes_closed_but_not_exited）。

    Windows 上 Python 子进程无法通过 os.close(1) 真正关闭 OS 管道句柄
    （STD_OUTPUT_HANDLE、C runtime _ioinfo 等多个引用），无法用真实子进程
    模拟"管道已 EOF 但进程未退出"场景。改用 mock 精准模拟此边界条件。
    """

    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout = _FakePipeStream(stdout)
        self.stderr = _FakePipeStream(stderr)
        self.stdin = None
        self.pid = 99999
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)


def test_run_command_returns_quickly_when_pipes_close_but_process_hangs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """管道关闭后进程挂死时，run_command 应快速返回已捕获的输出，不等待整体超时。

    借鉴 sw-factory test_provider_kills_process_when_pipes_closed_but_not_exited：
    用 _FakePopen 模拟"管道已 EOF 但进程未退出"。

    Windows 上 Python 子进程无法通过 os.close(1) 真正关闭 OS 管道句柄
    （STD_OUTPUT_HANDLE、C runtime _ioinfo 等多个引用），无法用真实子进程
    模拟此场景。改用 mock 精准模拟边界条件。

    修复前：process.wait(timeout=timeout_seconds) 会阻塞到整体超时（可能 2400s）。
    修复后：检测到 stdout/stderr reader 线程均结束（EOF）后，给短宽限期强杀，
    返回 return_code=0 让调用方校验 payload。
    """
    fake = _FakePopen(stdout="pipe-closed-output\n")
    monkeypatch.setattr(subprocess_utils.subprocess, "Popen", lambda *a, **kw: fake)
    monkeypatch.setattr(subprocess_utils, "terminate_process_tree", lambda pid: None)

    started = time.monotonic()
    result = run_command(
        [sys.executable, "fake"],
        cwd=tmp_path,
        timeout_seconds=60,
    )
    elapsed = time.monotonic() - started

    # 关键断言 1：不应等待整体超时（60s），应在轮询间隔（10s）+ 宽限期（10s）内返回
    assert elapsed < 25, (
        f"run_command 在管道关闭后挂死场景下耗时 {elapsed:.1f}s，"
        f"未触发 pipe-closed-dangling 检测（期望 < 25s）"
    )
    # 关键断言 2：输出应被完整捕获
    assert "pipe-closed-output" in result.stdout, (
        f"未捕获子进程输出，stdout={result.stdout!r}"
    )
    # 关键断言 3：return_code=0，让调用方通过 payload 校验决定真实成败
    assert result.return_code == 0, (
        f"pipe-closed-dangling 场景应返回 0 让调用方校验 payload，"
        f"实际 return_code={result.return_code}"
    )


def test_run_command_normal_exit_returns_actual_return_code(tmp_path: Path) -> None:
    """正常退出的子进程应返回实际 return code，不受 pipe-closed 检测影响。"""
    script_path = tmp_path / "normal_exit.py"
    script_path.write_text(
        "import sys\nprint('normal output')\nsys.exit(0)\n",
        encoding="utf-8",
    )

    result = run_command(
        [sys.executable, str(script_path)],
        cwd=tmp_path,
        timeout_seconds=30,
    )

    assert result.return_code == 0
    assert "normal output" in result.stdout


def test_run_command_normal_failure_returns_nonzero(tmp_path: Path) -> None:
    """正常失败的子进程（exit 1）应返回非零 return code。"""
    script_path = tmp_path / "normal_fail.py"
    script_path.write_text(
        "import sys\nsys.stderr.write('boom\\n')\nsys.exit(1)\n",
        encoding="utf-8",
    )

    result = run_command(
        [sys.executable, str(script_path)],
        cwd=tmp_path,
        timeout_seconds=30,
    )

    assert result.return_code == 1
    assert "boom" in result.stderr


def test_run_command_timeout_kills_process(tmp_path: Path) -> None:
    """超时应终止进程并返回 124。"""
    script_path = tmp_path / "slow.py"
    script_path.write_text(
        "import time\nprint('starting', flush=True)\ntime.sleep(120)\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    result = run_command(
        [sys.executable, str(script_path)],
        cwd=tmp_path,
        timeout_seconds=3,
    )
    elapsed = time.monotonic() - started

    assert result.return_code == 124
    assert elapsed < 20, f"超时后应快速返回，实际 {elapsed:.1f}s"
    assert "starting" in result.stdout
