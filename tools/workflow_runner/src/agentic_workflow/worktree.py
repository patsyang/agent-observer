from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorktreeState:
    base_commit: str
    branch: str
    path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "base_commit": self.base_commit,
            "branch": self.branch,
            "path": str(self.path),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WorktreeState":
        return cls(
            base_commit=str(payload["base_commit"]),
            branch=str(payload["branch"]),
            path=Path(str(payload["path"])),
        )


class WorktreeManager:
    def __init__(
        self,
        repo_root: Path,
        workspace_root: Path | None = None,
        *,
        worktrees_dir: Path | None = None,
        allowed_untracked_roots: tuple[Path, ...] = (),
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.workspace_root = workspace_root.resolve() if workspace_root else None
        self.worktrees_dir = worktrees_dir.resolve() if worktrees_dir else None
        self.allowed_untracked_roots = tuple(path.resolve() for path in allowed_untracked_roots)

    def create(self, *, workflow: str, run_id: str) -> WorktreeState:
        self._ensure_clean_git_root()
        base_commit = self._git("rev-parse", "HEAD")
        branch = self._branch_name(workflow, run_id)
        path = self._worktree_path(run_id)
        if path.exists():
            raise WorktreeError(f"worktree 已存在: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "-b", branch, str(path), base_commit)
        return WorktreeState(base_commit=base_commit, branch=branch, path=path)

    def cleanup(self, run_id: str, *, force: bool = False) -> bool:
        path = self._worktree_path(run_id)
        if not path.exists():
            return False
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        result = self._run_git(args, check=False)
        if result.returncode != 0:
            if force:
                shutil.rmtree(path, ignore_errors=True)
            else:
                raise WorktreeError(result.stderr.strip() or result.stdout.strip())
        self._run_git(["worktree", "prune"], check=False)
        return True

    def _ensure_clean_git_root(self) -> None:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise WorktreeError("当前目录不是 git worktree")
        dirty = self._dirty_paths()
        if dirty:
            raise WorktreeError("主工作区存在未提交变更，无法创建隔离 worktree")

    def _dirty_paths(self) -> list[str]:
        result = self._run_git(
            ["status", "--porcelain=v1", "--untracked-files=all"],
            check=True,
        )
        dirty = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            status = line[:2]
            rel_path = line[3:].strip()
            if " -> " in rel_path:
                rel_path = rel_path.split(" -> ", 1)[1]
            if status == "??" and self._is_allowed_untracked(rel_path):
                continue
            dirty.append(line)
        return dirty

    def _is_allowed_untracked(self, rel_path: str) -> bool:
        if not self.allowed_untracked_roots:
            return False
        candidate = (self.repo_root / rel_path).resolve()
        return any(
            candidate == root or candidate.is_relative_to(root)
            for root in self.allowed_untracked_roots
        )

    def _worktree_path(self, run_id: str) -> Path:
        if self.worktrees_dir is not None:
            return self.worktrees_dir / run_id
        if self.workspace_root is not None:
            return self.workspace_root / "worktrees" / run_id
        return self.repo_root / "output" / "worktrees" / run_id / "main"

    def _git(self, *args: str) -> str:
        result = self._run_git(list(args), check=True)
        return result.stdout.strip()

    def _run_git(
        self,
        args: list[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if check and result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or result.stdout.strip())
        return result

    def _branch_name(self, workflow: str, run_id: str) -> str:
        safe_workflow = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in workflow)
        return f"ao/{safe_workflow}/{run_id[:8]}"
