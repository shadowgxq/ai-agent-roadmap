"""Deterministic repository tools used by the Reactive baseline."""

from pathlib import Path

from ..contracts import ToolResult


def list_repository(
    workdir: Path,
    *,
    max_entries: int = 40,
) -> ToolResult:
    """List the repository root without reading file contents."""

    root = Path(workdir).resolve()
    operation_key = f"list_repository:{root}"
    if max_entries <= 0:
        raise ValueError("max_entries 必须大于 0")
    if not root.is_dir():
        return ToolResult(
            tool_name="list_repository",
            status="failed",
            operation_key=operation_key,
            error=f"工作目录不存在或不是目录：{root}",
        )

    try:
        entries = sorted(
            f"{entry.name}/" if entry.is_dir() else entry.name
            for entry in root.iterdir()
            if entry.name != ".git"
        )
    except OSError as exc:
        return ToolResult(
            tool_name="list_repository",
            status="failed",
            operation_key=operation_key,
            error=f"读取仓库目录失败：{type(exc).__name__}: {exc}",
        )

    visible_entries = entries[:max_entries]
    if len(entries) > max_entries:
        visible_entries.append(f"...（其余 {len(entries) - max_entries} 项未展示）")

    return ToolResult(
        tool_name="list_repository",
        status="succeeded",
        output="\n".join(visible_entries) or "（仓库根目录为空）",
        operation_key=operation_key,
    )
