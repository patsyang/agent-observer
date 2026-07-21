"""客户端版本号自动派生机制测试。

版本号策略：基于 collector_client 源码内容 hash，不依赖 git commit。
原因：git commit 是开发流程动作，与代码是否已改动无关。
未 commit 的改动也会影响打包出的客户端，必须反映在版本号中。
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

from app.collector_client import version as v


def test_base_version_is_simple_xy():
    # BASE 只在大版本时手改，必须是简单的 X.Y
    assert re.match(r"^\d+\.\d+$", v.BASE_CLIENT_VERSION), v.BASE_CLIENT_VERSION


def test_client_version_starts_with_base():
    assert v.COLLECTOR_CLIENT_VERSION.startswith(v.BASE_CLIENT_VERSION)


def test_content_hash_returns_hex_prefix():
    # content_hash 返回 8 位 hex
    h = v._content_hash()
    assert re.match(r"^[0-9a-f]{8}$", h), h


def test_content_hash_stable_across_calls():
    # 同一代码状态两次调用应返回相同值
    assert v._content_hash() == v._content_hash()


def test_content_hash_changes_when_source_changes(tmp_path, monkeypatch):
    # 改 collector_client 源码 → hash 变化
    original_hash = v._content_hash()
    # 模拟：用 monkeypatch 替换 _content_hash 的扫描根为一个临时目录
    fake_root = tmp_path / "fake_client"
    fake_root.mkdir()
    (fake_root / "__init__.py").write_text("# v1", encoding="utf-8")
    monkeypatch.setattr(v, "_CLIENT_ROOT", fake_root)
    h1 = v._content_hash()
    (fake_root / "__init__.py").write_text("# v2 changed", encoding="utf-8")
    h2 = v._content_hash()
    assert h1 != h2, "hash should change when source content changes"
    # 恢复后应与原始 hash 一致
    monkeypatch.undo()
    assert v._content_hash() == original_hash


def test_content_hash_ignores_build_version_file(tmp_path, monkeypatch):
    # _build_version.py 是烘焙产物，不能参与 hash（否则循环依赖）
    fake_root = tmp_path / "fake_client"
    fake_root.mkdir()
    (fake_root / "__init__.py").write_text("# stable", encoding="utf-8")
    (fake_root / "_build_version.py").write_text("BUILD_VERSION = '0.3.dev+aaaa1111'", encoding="utf-8")
    monkeypatch.setattr(v, "_CLIENT_ROOT", fake_root)
    h1 = v._content_hash()
    (fake_root / "_build_version.py").write_text("BUILD_VERSION = '0.3.dev+bbbb2222'", encoding="utf-8")
    h2 = v._content_hash()
    assert h1 == h2, "_build_version.py 不应参与 hash 计算"


def test_client_version_format_in_dev_env():
    # 开发环境（无 _build_version）：版本号 = BASE + ".dev+" + 8位hex
    version = v.COLLECTOR_CLIENT_VERSION
    assert re.match(rf"^{re.escape(v.BASE_CLIENT_VERSION)}\.dev\+[0-9a-f]{{8}}$", version), version


def test_baked_build_version_takes_priority(monkeypatch):
    # 模拟打包烘焙：_build_version 存在时优先于源码 hash
    mod = types.ModuleType("app.collector_client._build_version")
    mod.BUILD_VERSION = "9.9.baked999+deadbeef"
    monkeypatch.setitem(sys.modules, "app.collector_client._build_version", mod)
    assert v._resolve_client_version() == "9.9.baked999+deadbeef"


def test_corrupted_build_version_falls_back_to_hash(monkeypatch, tmp_path):
    """P1 回归：_build_version.py 损坏（SyntaxError 等）时应降级到源码 hash，不让 collector 启动崩溃。"""
    # 模拟 import 抛 SyntaxError（烘焙文件损坏）
    def _raise_syntax_error():
        raise SyntaxError("corrupted build version file")

    monkeypatch.setitem(
        sys.modules,
        "app.collector_client._build_version",
        None,  # 强制下次 import 重新触发
    )
    # 让 import 语句抛非 ImportError 异常
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "app.collector_client._build_version":
            raise SyntaxError("corrupted")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # 应降级到源码 hash 路径，而不是崩溃
    result = v._resolve_client_version()
    assert result.startswith(f"{v.BASE_CLIENT_VERSION}.dev+")
    # 不应是 unknown（因为真实源码 hash 能算出来）
    assert not result.endswith("unknown"), result


def test_content_hash_changes_on_file_add_remove(tmp_path, monkeypatch):
    """P2-3: 文件新增/删除应触发 hash 变化。"""
    fake_root = tmp_path / "fake_client"
    fake_root.mkdir()
    (fake_root / "__init__.py").write_text("# base", encoding="utf-8")
    monkeypatch.setattr(v, "_CLIENT_ROOT", fake_root)
    h1 = v._content_hash()
    # 新增文件
    (fake_root / "new_module.py").write_text("# new", encoding="utf-8")
    h2 = v._content_hash()
    assert h1 != h2, "新增文件应改变 hash"
    # 删除文件
    (fake_root / "new_module.py").unlink()
    h3 = v._content_hash()
    assert h2 != h3, "删除文件应改变 hash"
    assert h1 == h3, "恢复后 hash 应一致"


def test_content_hash_covers_subdirectory_files(tmp_path, monkeypatch):
    """P2-4: 子目录文件路径用 as_posix() 归一化，跨平台一致。"""
    fake_root = tmp_path / "fake_client"
    fake_root.mkdir()
    (fake_root / "__init__.py").write_text("# root", encoding="utf-8")
    sources_dir = fake_root / "sources"
    sources_dir.mkdir()
    (sources_dir / "codex.py").write_text("# codex source", encoding="utf-8")
    monkeypatch.setattr(v, "_CLIENT_ROOT", fake_root)
    h1 = v._content_hash()
    # 修改子目录文件内容
    (sources_dir / "codex.py").write_text("# codex source v2", encoding="utf-8")
    h2 = v._content_hash()
    assert h1 != h2, "子目录文件内容变化应改变 hash"
    # 验证 hash 格式正确（8 位 hex）
    assert re.match(r"^[0-9a-f]{8}$", h1), h1


def test_resolve_client_version_falls_back_to_unknown_when_hash_empty(monkeypatch):
    """P2-1/P2-2: hash 计算失败时版本号应为 BASE.dev+unknown，避免被误认为正式版。"""
    monkeypatch.setattr(v, "_content_hash", lambda: "")
    # 确保 _build_version 不存在
    monkeypatch.setitem(sys.modules, "app.collector_client._build_version", None)
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "app.collector_client._build_version":
            raise ImportError("not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = v._resolve_client_version()
    assert result == f"{v.BASE_CLIENT_VERSION}.dev+unknown", result
