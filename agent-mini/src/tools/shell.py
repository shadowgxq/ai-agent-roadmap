"""把 Executor 适配为模型可调用的 Shell 工具。"""

from pathlib import Path

from ..agent.config import ConfirmCallback
from ..execution.executor import Executor, LocalExecutor
from ..execution.workspace import Workspace, as_workspace
from .policy import Policy
from .registry import ToolExecutionResult, ToolRegistry


def register_shell_tools(
    registry: ToolRegistry,
    workdir: Path | Workspace,
    *,
    executor: Executor | None = None,
    timeout: float = 30.0,
    max_output_chars: int = 10_000,
    policy: Policy | None = None,
    on_confirm: ConfirmCallback | None = None,
) -> None:
    """把一个 Executor 注册成 run_shell 工具。

    ``executor`` 未注入时保留旧行为，自动创建 LocalExecutor；Runtime
    可以注入 DockerExecutor，工具和 Agent Loop 无需知道执行位置。
    """
    workspace = as_workspace(workdir)
    selected_executor = executor or LocalExecutor(
        workspace,
        timeout=timeout,
        max_output_chars=max_output_chars,
        policy=policy,
        on_confirm=on_confirm,
    )

    @registry.tool
    async def run_shell(command: str) -> str | ToolExecutionResult:
        """在当前 Executor 绑定的工作区中执行 Shell 命令。

        Args:
            command: 要执行的 Shell 命令。
        """
        result = await selected_executor.execute(command)
        return ToolExecutionResult(
            content=result.content,
            is_error=result.is_error,
        )
