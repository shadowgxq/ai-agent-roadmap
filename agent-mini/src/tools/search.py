"""工作目录内的文本搜索工具。"""

import os
import re
from collections.abc import Iterator
from pathlib import Path

from .fs import resolve_path
from .registry import ToolRegistry


IGNORED_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


def _iter_files(target: Path, root: Path) -> Iterator[Path]:
    """按名称顺序遍历文件，并跳过常见依赖和缓存目录。"""
    if target.is_file():
        yield target
        return

    for current_dir, dirnames, filenames in os.walk(target):
        dirnames[:] = sorted(
            (name for name in dirnames if name not in IGNORED_DIRS),
            key=str.lower,
        )
        for filename in sorted(filenames, key=str.lower):
            file_path = Path(current_dir) / filename
            resolved = file_path.resolve()
            if resolved.is_relative_to(root):
                yield resolved


def register_search_tools(
    registry: ToolRegistry,
    workdir: Path,
) -> None:
    """注册绑定到指定工作目录的搜索工具。"""
    root = workdir.resolve()

    @registry.tool
    def grep(
        pattern: str,
        path: str = ".",
        max_results: int = 100,
    ) -> str:
        """在文件或目录中搜索正则表达式。

        Args:
            pattern: 要搜索的正则表达式。
            path: 搜索起点，默认为工作目录。
            max_results: 最多返回的匹配数量。
        """
        if not pattern:
            raise ValueError("pattern 不能为空")
        if max_results < 1:
            raise ValueError("max_results 必须大于等于 1")

        target = resolve_path(root, path)
        if not target.exists():
            raise FileNotFoundError(f"路径不存在：{path}")
        if not target.is_file() and not target.is_dir():
            raise ValueError(f"路径不是普通文件或目录：{path}")

        try:
            expression = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"无效正则表达式：{exc}") from exc

        matches: list[str] = []
        for file_path in _iter_files(target, root):
            try:
                with file_path.open("r", encoding="utf-8") as file:
                    for line_number, line in enumerate(file, start=1):
                        if "\x00" in line:
                            break
                        if not expression.search(line):
                            continue

                        relative_path = file_path.relative_to(root).as_posix()
                        text = line.rstrip("\r\n")
                        if len(text) > 500:
                            text = f"{text[:500]}...(行内容已截断)"
                        matches.append(
                            f"{relative_path}:{line_number}:{text}"
                        )

                        if len(matches) >= max_results:
                            matches.append("...(搜索结果已达到上限)")
                            return "\n".join(matches)
            except (OSError, UnicodeError):
                continue

        if not matches:
            return "(没有找到匹配内容)"
        return "\n".join(matches)
