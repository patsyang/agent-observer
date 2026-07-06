"""客户端版本号自动派生机制测试。"""
from __future__ import annotations

import re
import sys
import types

from app.collector_client import version as v


def test_base_version_is_simple_xy():
    # BASE 只在大版本时手改，必须是简单的 X.Y
    assert re.match(r"^\d+\.\d+$", v.BASE_CLIENT_VERSION), v.BASE_CLIENT_VERSION


def test_client_version_starts_with_base():
    assert v.COLLECTOR_CLIENT_VERSION.startswith(v.BASE_CLIENT_VERSION)


def test_git_suffix_format_in_repo():
    # 测试在 git 仓库里跑 → 版本应含 .dev<提交数>+<短sha>
    suffix = v._git_suffix()
    assert suffix, "expected non-empty git suffix when running inside a git repo"
    assert re.match(r"^\.dev\d+\+[0-9a-f]{7,}$", suffix), suffix
    assert v.COLLECTOR_CLIENT_VERSION == v.BASE_CLIENT_VERSION + suffix


def test_baked_build_version_takes_priority(monkeypatch):
    # 模拟打包烘焙：_build_version 存在时优先于 git 派生
    mod = types.ModuleType("app.collector_client._build_version")
    mod.BUILD_VERSION = "9.9.baked999+deadbeef"
    monkeypatch.setitem(sys.modules, "app.collector_client._build_version", mod)
    assert v._resolve_client_version() == "9.9.baked999+deadbeef"
