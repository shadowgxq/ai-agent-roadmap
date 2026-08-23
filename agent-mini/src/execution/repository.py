"""Repository 到临时 Workspace 的生命周期边界。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .workspace import LocalWorkspace


class RepositoryError(RuntimeError):
    """Repository 探测、checkout 或清理失败。"""


def _run_git(
    cwd: Path,
    *arguments: str,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """以 argv 方式执行 Git，避免把 ref/path 交给 Shell 解析。"""
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RepositoryError(f"Git 命令不可用或超时: {arguments}") from exc


@dataclass(frozen=True)
class Repository:
    """一个可创建临时 Worktree 的 Git Repository。"""

    root: Path

    @classmethod
    def discover(cls, path: Path) -> "Repository":
        """从任意仓库子目录向上发现 Git 根目录。"""
        result = _run_git(path.resolve(), "rev-parse", "--show-toplevel")
        if result.returncode != 0 or not result.stdout.strip():
            raise RepositoryError(f"不是 Git Repository: {path}")
        return cls(Path(result.stdout.strip()).resolve())

    @property
    def head_sha(self) -> str:
        """返回临时工作区的默认 checkout 起点。"""
        result = _run_git(self.root, "rev-parse", "HEAD")
        if result.returncode != 0 or not result.stdout.strip():
            raise RepositoryError(result.stderr.strip() or "Repository 没有 HEAD")
        return result.stdout.strip()

    def open_workspace(self, *, ref: str = "HEAD") -> "RepositoryWorkspace":
        """创建一个由调用方 with 管理的临时 Worktree。"""
        return RepositoryWorkspace(self, ref=ref)


class RepositoryWorkspace:
    """Git Worktree 与 LocalWorkspace 的可清理组合。"""

    def __init__(self, repository: Repository, *, ref: str = "HEAD") -> None:
        if not ref.strip():
            raise ValueError("Git ref 不能为空")
        self.repository = repository
        self.ref = ref
        self._path: Path | None = None
        self._workspace: LocalWorkspace | None = None

    @property
    def root(self) -> Path:
        """返回已打开的临时工作区根目录。"""
        if self._workspace is None:
            raise RepositoryError("RepositoryWorkspace 尚未打开")
        return self._workspace.root

    def resolve(self, path: str | Path = ".") -> Path:
        """将 Workspace 的路径边界转发给临时 LocalWorkspace。"""
        if self._workspace is None:
            raise RepositoryError("RepositoryWorkspace 尚未打开")
        return self._workspace.resolve(path)

    def __enter__(self) -> "RepositoryWorkspace":
        if self._workspace is not None:
            raise RepositoryError("RepositoryWorkspace 不能重复打开")

        temporary_path = Path(
            tempfile.mkdtemp(prefix="agent-mini-worktree-")
        )
        # git worktree add 要求目标不存在；父目录仍是系统临时目录，范围明确。
        temporary_path.rmdir()
        result = _run_git(
            self.repository.root,
            "worktree",
            "add",
            "--detach",
            str(temporary_path),
            self.ref,
        )
        if result.returncode != 0:
            shutil.rmtree(temporary_path, ignore_errors=True)
            raise RepositoryError(
                result.stderr.strip() or "无法创建 Git 临时 Worktree"
            )

        try:
            self._path = temporary_path
            self._workspace = LocalWorkspace(temporary_path)
        except Exception:
            self._remove_worktree(temporary_path)
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        path = self._path
        self._workspace = None
        self._path = None
        if path is not None:
            self._remove_worktree(path)

    def _remove_worktree(self, path: Path) -> None:
        result = _run_git(
            self.repository.root,
            "worktree",
            "remove",
            "--force",
            str(path),
        )
        if result.returncode != 0 and path.exists():
            # 只清理本次明确创建的临时路径，不能扩大到 Repository 根目录。
            shutil.rmtree(path, ignore_errors=True)
        if result.returncode != 0:
            raise RepositoryError(
                result.stderr.strip() or "无法清理 Git 临时 Worktree"
            )


__all__ = ["Repository", "RepositoryError", "RepositoryWorkspace"]
