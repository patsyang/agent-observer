"""客户端版本号：基于源码内容 hash 自动派生，无需手动维护。

策略（优先级从高到低）：
1. 打包烘焙的 ``_build_version.BUILD_VERSION`` —— 客户端运行时读这个（客户端机器无源码）。
2. 开发环境：``BASE + ".dev+" + <collector_client 源码内容 hash[:8]>`` —— 代码改动自动变。
3. 兜底：``BASE``（计算 hash 失败时降级）。

为什么不用 git commit：
- git commit 是开发流程动作，与"代码是否已改动"不同步。
- 未 commit 的改动也会影响打包出的客户端，必须反映在版本号中。
- 所以用 collector_client 源码内容 hash：代码改了（无论是否 commit）→ hash 变 → 版本号变。

调用方永远只读 ``COLLECTOR_CLIENT_VERSION``，不关心它怎么来的。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# 基线版本：只在发大版本（major/minor）时手改一次。
BASE_CLIENT_VERSION = "0.3"
COLLECTOR_PROTOCOL_VERSION = "agent-observer-telemetry/v3"

# collector_client 目录根：用于计算源码内容 hash。
# 暴露为模块级变量，便于测试 monkeypatch。
_CLIENT_ROOT = Path(__file__).resolve().parent

# 不参与 hash 的文件：烘焙产物，避免循环依赖。
_EXCLUDED_FILES = {"_build_version.py"}


def _content_hash() -> str:
    """返回 collector_client 目录下所有 .py 文件内容的 sha1 短 hash。

    代码改动 → hash 变 → 版本号变。不依赖 git，未 commit 的改动也能反映。
    文件路径（相对）+ 文件内容都参与 hash，文件改名/新增/删除/内容修改都会触发变化。
    """
    try:
        hasher = hashlib.sha1()
        files = sorted(_CLIENT_ROOT.rglob("*.py"))
        if not files:
            return ""
        for path in files:
            if path.name in _EXCLUDED_FILES:
                continue
            rel = path.relative_to(_CLIENT_ROOT).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(path.read_bytes())
            hasher.update(b"\0")
        return hasher.hexdigest()[:8]
    except Exception:
        return ""


def _resolve_client_version() -> str:
    # 1. 打包烘焙值（客户端运行时优先读这个）
    # 用宽异常：烘焙文件可能损坏（zip 解压不完整、磁盘错误、人工误编辑），
    # 此时 SyntaxError/NameError 等不应让 collector 启动崩溃，应降级到源码 hash。
    try:
        from app.collector_client._build_version import BUILD_VERSION  # type: ignore
        if BUILD_VERSION:
            return BUILD_VERSION
    except Exception:
        pass
    # 2. 开发环境：基于源码内容 hash
    h = _content_hash()
    if h:
        return f"{BASE_CLIENT_VERSION}.dev+{h}"
    # 3. 兜底：hash 计算失败时用 unknown 标记，避免被误认为正式发布版
    return f"{BASE_CLIENT_VERSION}.dev+unknown"


COLLECTOR_CLIENT_VERSION = _resolve_client_version()
