"""客户端版本号：自动派生，无需手动维护。

策略（优先级从高到低）：
1. 打包烘焙的 ``_build_version.BUILD_VERSION`` —— 客户端运行时读这个（客户端机器无 git）。
2. 开发环境：``BASE + ".dev<提交数>+<短sha>"`` —— 从 git 算，**每次 commit 自动变**。
3. 兜底：``BASE``（非 git 环境 graceful 降级）。

调用方永远只读 ``COLLECTOR_CLIENT_VERSION``，不关心它怎么来的。
所以：改了客户端代码 → 新 commit → 版本号自动不同，**永远不需要手升、不会忘**。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# 基线版本：只在发大版本（major/minor）时手改一次。
BASE_CLIENT_VERSION = "0.3"
COLLECTOR_PROTOCOL_VERSION = "agent-observer-telemetry/v3"

# version.py 位于 <repo>/backend/app/collector_client/version.py → parents[3] = 仓库根
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _git_suffix() -> str:
    """返回 ``.dev<提交数>+<短sha>``；非 git 仓库或无 git 时返回 ``''``。"""
    try:
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(_REPO_ROOT), stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_REPO_ROOT), stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        if count and sha:
            return f".dev{count}+{sha}"
    except Exception:
        pass
    return ""


def _resolve_client_version() -> str:
    # 1. 打包烘焙值（客户端运行时优先读这个）
    try:
        from app.collector_client._build_version import BUILD_VERSION  # type: ignore
        if BUILD_VERSION:
            return BUILD_VERSION
    except ImportError:
        pass
    # 2. 开发环境：从 git 派生
    return BASE_CLIENT_VERSION + _git_suffix()


COLLECTOR_CLIENT_VERSION = _resolve_client_version()
