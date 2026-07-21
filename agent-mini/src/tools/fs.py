"""工作目录内的文件操作工具。"""

from pathlib import Path

from .registry import ToolRegistry


def resolve_path(workdir: Path, path: str) -> Path:
    """解析工作目录内的路径，并拒绝越界访问。"""
    root = workdir.resolve()
    target = (root / path).resolve()

    if not target.is_relative_to(root):
        raise ValueError(f"路径超出工作目录：{path}")

    return target


def register_fs_tools(
    registry: ToolRegistry,
    workdir: Path,
) -> None:
    """注册绑定到指定工作目录的文件工具。"""

    @registry.tool
    def read_file(
        path: str,
        offset: int = 1,
        limit: int = 200,
    ) -> str:
        """读取工作目录内的 UTF-8 文本文件。

        Args:
            path: 相对于工作目录的文件路径。
            offset: 起始行号，从 1 开始。
            limit: 最多返回的行数。
        """
        if offset < 1:
            raise ValueError("offset 必须大于等于 1")
        if limit < 1:
            raise ValueError("limit 必须大于等于 1")

        target = resolve_path(workdir, path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在：{path}")
        if not target.is_file():
            raise IsADirectoryError(f"路径不是文件：{path}")

        lines = target.read_text(encoding="utf-8").splitlines()
        start = offset - 1
        return "\n".join(lines[start:start + limit])

    @registry.tool
    def list_dir(path: str = ".") -> str:
        """列出工作目录内指定目录的直接子项。

        Args:
            path: 相对于工作目录的目录路径，默认为工作目录。
        """
        target = resolve_path(workdir, path)
        if not target.exists():
            raise FileNotFoundError(f"路径不存在：{path}")
        if not target.is_dir():
            raise IsADirectoryError(f"路径不是目录：{path}")

        entries = sorted(
            target.iterdir(),
            key=lambda entry: entry.name.lower(),
        )
        if not entries:
            return "(目录为空)"

        lines = []
        for entry in entries:
            kind = "DIR" if entry.is_dir() else "FILE"
            lines.append(f"[{kind}] {entry.name}")
        return "\n".join(lines)

    @registry.tool
    def write_file(path: str, content: str) -> str:
        """创建或覆盖工作目录内的 UTF-8 文本文件。

        Args:
            path: 相对于工作目录的文件路径。
            content: 要写入文件的完整内容。
        """
        target = resolve_path(workdir, path)
        if target.exists() and target.is_dir():
            raise IsADirectoryError(f"路径是目录：{path}")

        target.parent.mkdir(parents=True, exist_ok=True)
        written = target.write_text(content, encoding="utf-8")
        return f"已写入文件：{path}，共 {written} 个字符"

    @registry.tool
    def edit_file(path: str, old_string: str, new_string: str) -> str:
        """精确替换已有文本文件中的唯一字符串。

        Args:
            path: 相对于工作目录的文件路径。
            old_string: 文件中需要替换的原始字符串，必须只出现一次。
            new_string: 替换后的字符串。
        """
        if not old_string:
            raise ValueError("old_string 不能为空")

        target = resolve_path(workdir, path)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在：{path}")
        if not target.is_file():
            raise IsADirectoryError(f"路径不是文件：{path}")

        content = target.read_text(encoding="utf-8")
        occurrences = content.count(old_string)
        if occurrences == 0:
            raise ValueError("文件中找不到 old_string")
        if occurrences > 1:
            raise ValueError(
                f"old_string 在文件中出现 {occurrences} 次，无法唯一替换"
            )

        updated = content.replace(old_string, new_string, 1)
        target.write_text(updated, encoding="utf-8")
        return f"已更新文件：{path}"
