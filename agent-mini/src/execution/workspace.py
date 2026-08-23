"""受控代码工作区抽象。

Workspace 只负责“Agent 能看见和修改哪些文件”，不负责执行 Shell。
当前实现是本地目录，后续 DockerWorkspace 可以复用同一份工具边界。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable


class WorkspaceError(ValueError):
    """工作区路径或文件操作不满足安全边界。"""


@runtime_checkable
class Workspace(Protocol):
    """文件工具依赖的最小工作区协议。"""

    @property
    def root(self) -> Path:
        """返回工作区的绝对根目录。"""

    def resolve(self, path: str | Path = ".") -> Path:
        """解析工作区内的相对路径，并拒绝越界访问。"""


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


__all__ = ["LocalWorkspace", "Workspace", "WorkspaceError", "as_workspace"]
