"""Coding Agent 的执行边界：工作区、执行器和 Sandbox。"""

from .workspace import LocalWorkspace, Workspace, WorkspaceError, as_workspace

__all__ = ["LocalWorkspace", "Workspace", "WorkspaceError", "as_workspace"]
