"""Coding Agent 的执行边界：工作区、执行器和 Sandbox。"""

from .executor import (
    DockerExecutor,
    ExecutionResult,
    ExecutionStatus,
    Executor,
    LocalExecutor,
    truncate_output,
)
from .repository import Repository, RepositoryError, RepositoryWorkspace
from .workspace import (
    FileDiff,
    LocalWorkspace,
    Workspace,
    WorkspaceError,
    as_workspace,
)

__all__ = [
    "DockerExecutor",
    "ExecutionResult",
    "ExecutionStatus",
    "Executor",
    "FileDiff",
    "LocalExecutor",
    "LocalWorkspace",
    "Repository",
    "RepositoryError",
    "RepositoryWorkspace",
    "Workspace",
    "WorkspaceError",
    "as_workspace",
    "truncate_output",
]
