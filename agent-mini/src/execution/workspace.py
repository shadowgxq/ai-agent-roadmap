"""受控代码工作区抽象。

Workspace 只负责“Agent 能看见和修改哪些文件”，不负责执行 Shell。
当前实现是本地目录，后续 DockerWorkspace 可以复用同一份工具边界。
"""

from __future__ import annotations

import os
import difflib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable


class WorkspaceError(ValueError):
    """工作区路径或文件操作不满足安全边界。"""


DiffStatus = Literal["added", "modified", "deleted", "binary"]


@dataclass(frozen=True)
class FileDiff:
    """一个文件变更的可序列化摘要。"""

    path: str
    status: DiffStatus
    patch: str
    additions: int
    deletions: int
    binary: bool = False
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        """转换为 Agent Event metadata 使用的普通字典。"""
        return {
            "path": self.path,
            "status": self.status,
            "patch": self.patch,
            "additions": self.additions,
            "deletions": self.deletions,
            "binary": self.binary,
            "truncated": self.truncated,
        }


@runtime_checkable
class Workspace(Protocol):
    """文件工具依赖的最小工作区协议。"""

    @property
    def root(self) -> Path:
        """返回工作区的绝对根目录。"""

    def resolve(self, path: str | Path = ".") -> Path:
        """解析工作区内的相对路径，并拒绝越界访问。"""

    def snapshot_file(self, path: str | Path) -> bytes | None:
        """读取一个文件的变更前快照；文件不存在时返回 None。"""

    def diff_file(self, path: str | Path, before: bytes | None) -> FileDiff:
        """根据变更前快照生成结构化 Diff。"""


class LocalWorkspace:
    """把一个本地目录封装成受控 Workspace。"""

    def __init__(self, root: Path) -> None:
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.exists():
            raise FileNotFoundError(f"工作区不存在: {resolved_root}")
        if not resolved_root.is_dir():
            raise NotADirectoryError(f"工作区不是目录: {resolved_root}")
        self._root = resolved_root

    @property
    def root(self) -> Path:
        return self._root

    def resolve(self, path: str | Path = ".") -> Path:
        """解析路径；即使目标尚不存在，也校验现有父级和最终路径。"""
        raw_path = Path(path)
        target = (self._root / raw_path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise WorkspaceError(
                f"路径超出工作区: {path} (root={self._root})"
            ) from exc
        return target

    def relative_path(self, path: str | Path) -> str:
        """返回适合事件和日志展示的 POSIX 相对路径。"""
        return self.resolve(path).relative_to(self._root).as_posix()

    def read_text(self, path: str | Path, *, encoding: str = "utf-8") -> str:
        """读取工作区内的文本文件。"""
        target = self.resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        if not target.is_file():
            raise IsADirectoryError(f"路径不是文件: {path}")
        return target.read_text(encoding=encoding)

    def write_text(
        self,
        path: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> int:
        """创建或覆盖工作区内的文本文件。"""
        target = self.resolve(path)
        if target.exists() and target.is_dir():
            raise IsADirectoryError(f"路径是目录: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target.write_text(content, encoding=encoding)

    def snapshot_file(self, path: str | Path) -> bytes | None:
        """读取文件快照，不把目录或工作区外的路径纳入 Diff。"""
        target = self.resolve(path)
        if not target.exists():
            return None
        if not target.is_file():
            raise IsADirectoryError(f"路径不是文件: {path}")
        return target.read_bytes()

    def diff_file(self, path: str | Path, before: bytes | None) -> FileDiff:
        """生成受长度限制的 unified diff。"""
        relative_path = self.relative_path(path)
        after = self.snapshot_file(path)
        status: DiffStatus
        if before is None and after is None:
            raise WorkspaceError(f"文件变更不存在: {relative_path}")
        if before is None:
            status = "added"
        elif after is None:
            status = "deleted"
        else:
            status = "modified"

        binary = any(
            content is not None
            and (b"\x00" in content or _decode_text(content) is None)
            for content in (before, after)
        )
        if binary:
            return FileDiff(
                path=relative_path,
                status="binary",
                patch="",
                additions=0,
                deletions=0,
                binary=True,
            )

        before_text = _decode_text(before) or ""
        after_text = _decode_text(after) or ""
        diff_lines = list(
            difflib.unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        additions = sum(
            line.startswith("+") and not line.startswith("+++")
            for line in diff_lines
        )
        deletions = sum(
            line.startswith("-") and not line.startswith("---")
            for line in diff_lines
        )
        patch = "\n".join(diff_lines)
        truncated = len(patch) > MAX_DIFF_CHARS
        if truncated:
            patch = (
                patch[:MAX_DIFF_CHARS]
                + "\n...(Diff 内容已截断)..."
            )
        return FileDiff(
            path=relative_path,
            status=status,
            patch=patch,
            additions=additions,
            deletions=deletions,
            truncated=truncated,
        )

    def list_dir(self, path: str | Path = ".") -> list[Path]:
        """返回目录的直接子项，按名称排序。"""
        target = self.resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"路径不存在: {path}")
        if not target.is_dir():
            raise NotADirectoryError(f"路径不是目录: {path}")
        return sorted(target.iterdir(), key=lambda entry: entry.name.lower())

    def iter_files(
        self,
        path: str | Path = ".",
        *,
        ignored_dirs: set[str] | frozenset[str] = frozenset(),
    ) -> Iterator[Path]:
        """在工作区内遍历文件，并再次校验软链接解析结果。"""
        target = self.resolve(path)
        if target.is_file():
            yield target
            return
        if not target.is_dir():
            raise ValueError(f"路径不是普通文件或目录: {path}")

        for current_dir, dirnames, filenames in os.walk(target):
            dirnames[:] = sorted(
                (name for name in dirnames if name not in ignored_dirs),
                key=str.lower,
            )
            for filename in sorted(filenames, key=str.lower):
                file_path = Path(current_dir) / filename
                resolved = file_path.resolve()
                try:
                    resolved.relative_to(self._root)
                except ValueError:
                    continue
                yield resolved


def as_workspace(value: Path | Workspace) -> Workspace:
    """兼容旧的 Path 调用方，并统一返回 Workspace。"""
    if isinstance(value, LocalWorkspace):
        return value
    if isinstance(value, Path):
        return LocalWorkspace(value)
    if isinstance(value, Workspace):
        return value
    raise TypeError("workdir 必须是 Path 或 Workspace")


MAX_DIFF_CHARS = 24_000


def _decode_text(value: bytes | None) -> str | None:
    if value is None:
        return ""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


__all__ = [
    "DiffStatus",
    "FileDiff",
    "LocalWorkspace",
    "Workspace",
    "WorkspaceError",
    "as_workspace",
]
