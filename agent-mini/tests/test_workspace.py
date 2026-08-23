import asyncio
from pathlib import Path

import pytest

from src.execution.workspace import LocalWorkspace, WorkspaceError
from src.tools.fs import register_fs_tools
from src.tools.registry import ToolRegistry
from src.tools.search import register_search_tools


def test_local_workspace_rejects_escape_and_resolves_relative_paths(
    tmp_path: Path,
):
    workspace = LocalWorkspace(tmp_path)
    assert workspace.resolve("src/main.py") == tmp_path / "src/main.py"

    with pytest.raises(WorkspaceError):
        workspace.resolve("../outside.txt")


def test_fs_tools_use_workspace_boundary(tmp_path: Path):
    registry = ToolRegistry()
    register_fs_tools(registry, LocalWorkspace(tmp_path))

    result = asyncio.run(
        registry.execute_with_status(
            "write_file",
            {"path": "src/main.py", "content": "print('ok')"},
        )
    )
    assert result.is_error is False
    assert (tmp_path / "src/main.py").read_text() == "print('ok')"

    escaped = asyncio.run(
        registry.execute_with_status(
            "read_file",
            {"path": "../outside.txt"},
        )
    )
    assert escaped.is_error is True


def test_search_tool_only_returns_files_inside_workspace(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.py").write_text("needle = True\n")
    registry = ToolRegistry()
    register_search_tools(registry, LocalWorkspace(tmp_path))

    result = asyncio.run(
        registry.execute("grep", {"pattern": "needle", "path": "src"})
    )
    assert "src/main.py:1:needle = True" in result
