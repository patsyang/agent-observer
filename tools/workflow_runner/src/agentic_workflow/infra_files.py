from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TEXT_NAMES = {".gitignore", ".gitkeep"}
TEXT_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class InfraFile:
    path: str
    source: Path
    render: bool


def iter_managed_files(infra_root: Path, manifest: dict[str, Any]) -> list[InfraFile]:
    files = iter_template_files(infra_root, manifest, "managed_files")
    for directory in manifest.get("managed_directories", []):
        root = infra_root / Path(directory.get("source") or directory["path"])
        target_root = normalize_path(directory["path"])
        excludes = tuple(directory.get("exclude", []))
        for source in sorted(path for path in root.rglob("*") if path.is_file()):
            rel = source.relative_to(root)
            if is_excluded(rel, excludes):
                continue
            files.append(
                InfraFile(
                    path=normalize_path(Path(target_root) / rel),
                    source=source,
                    render=False,
                )
            )
    return sorted(files, key=lambda item: item.path)


def iter_template_files(
    infra_root: Path,
    manifest: dict[str, Any],
    key: str,
) -> list[InfraFile]:
    template_root = infra_root / Path(manifest["template_root"])
    result = []
    for item in manifest.get(key, []):
        target_path = normalize_path(item["path"])
        source_path = normalize_path(item.get("source") or item["path"])
        result.append(
            InfraFile(
                path=target_path,
                source=template_root / Path(source_path),
                render=True,
            )
        )
    return result


def write_entry(target_root: Path, entry: InfraFile, variables: dict[str, str]) -> None:
    target = target_root / Path(entry.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not entry.source.exists():
        raise ValueError(f"template source not found: {entry.source}")
    target.write_bytes(entry_bytes(entry, variables))


def entry_bytes(entry: InfraFile, variables: dict[str, str]) -> bytes:
    if entry.render and is_text_file(entry.source):
        text = entry.source.read_bytes().decode("utf-8")
        for name, value in variables.items():
            text = text.replace("{{" + name + "}}", value)
        return text.encode("utf-8")
    return entry.source.read_bytes()


def build_variables(project_name: str) -> dict[str, str]:
    slug = re.sub(r"[^a-z0-9_]+", "_", project_name.lower()).strip("_")
    return {
        "PROJECT_NAME": project_name,
        "PROJECT_SLUG": slug or "project",
    }


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def update_status(
    current_hash: str | None,
    baseline_hash: str | None,
    infra_hash: str,
) -> str:
    if current_hash is None:
        return "missing"
    if baseline_hash is None:
        return "new_managed"
    local_changed = current_hash != baseline_hash
    infra_changed = infra_hash != baseline_hash
    if not local_changed and not infra_changed:
        return "unchanged"
    if not local_changed and infra_changed:
        return "would_update"
    if local_changed and not infra_changed:
        return "local_modified"
    return "conflict"


def baseline_hash(value: Any) -> str | None:
    if isinstance(value, dict):
        hash_value = value.get("sha256")
        return str(hash_value) if hash_value else None
    if isinstance(value, str):
        return value
    return None


def is_text_file(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def is_excluded(relative_path: Path, patterns: tuple[str, ...]) -> bool:
    names = set(relative_path.parts)
    for pattern in patterns:
        if pattern in names:
            return True
        posix_path = relative_path.as_posix()
        if fnmatch.fnmatch(posix_path, pattern) or fnmatch.fnmatch(relative_path.name, pattern):
            return True
    return False


def normalize_path(path: str | Path) -> str:
    return Path(path).as_posix()
