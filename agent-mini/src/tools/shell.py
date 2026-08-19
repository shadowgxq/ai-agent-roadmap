"""在指定工作目录内执行 Shell 命令。"""

import asyncio
import inspect
import os
from pathlib import Path
import sys

from ..agent.config import ConfirmCallback
from .policy import Policy, PolicyAction
from .registry import ToolExecutionResult, ToolRegistry


def _truncate_output(output: str, max_chars: int) -> str:
    """输出过长时保留头尾，并截断中间部分。"""
    if len(output) <= max_chars:
        return output

    marker = "\n...(中间内容已截断)...\n"
    if max_chars <= len(marker):
        return output[:max_chars]

    remaining = max_chars - len(marker)
    head_chars = remaining // 2
    tail_chars = remaining - head_chars
    return f"{output[:head_chars]}{marker}{output[-tail_chars:]}"


def register_shell_tools(
    registry: ToolRegistry,
    workdir: Path,
    *,
    timeout: float = 30.0,
    max_output_chars: int = 10_000,
    policy: Policy | None = None,
    on_confirm: ConfirmCallback | None = None,
) -> None:
    """注册绑定到指定工作目录的 Shell 工具。"""
    if timeout <= 0:
        raise ValueError("timeout 必须大于 0")
    if max_output_chars <= 0:
        raise ValueError("max_output_chars 必须大于 0")

    root = workdir.resolve()
    shell_policy = policy if policy is not None else Policy()
    environment = os.environ.copy()
    if os.name != "nt":
        path_entries = [
            str(Path(sys.executable).parent),
            str(Path.home() / ".local" / "bin"),
            environment.get("PATH", ""),
        ]
        environment["PATH"] = os.pathsep.join(
            entry for entry in path_entries if entry
        )
        for temp_variable in ("TMPDIR", "TMP", "TEMP"):
            environment[temp_variable] = "/tmp"

    @registry.tool
    async def run_shell(command: str) -> str | ToolExecutionResult:
        """在项目工作目录中执行 Shell 命令。

        Args:
            command: 要执行的 Shell 命令。
        """
        if not command.strip():
            raise ValueError("command 不能为空")

        decision = shell_policy.evaluate(command)
        if decision.action is PolicyAction.DENY:
            return ToolExecutionResult(
                content=(
                    f"命令拒绝，未执行: {command}\n"
                    f"原因: {decision.reason}"
                ),
                is_error=True,
            )

        if decision.action is PolicyAction.CONFIRM:
            if on_confirm is None:
                return ToolExecutionResult(
                    content=(
                        f"命令需要确认，但当前未配置确认回调，未执行: {command}\n"
                        f"原因: {decision.reason}"
                    ),
                    is_error=True,
                )

            approved = on_confirm(command, decision.reason)
            if inspect.isawaitable(approved):
                approved = await approved
            if not approved:
                return ToolExecutionResult(
                    content=(
                        f"用户拒绝了命令，未执行: {command}\n"
                        f"原因: {decision.reason}"
                    ),
                    is_error=True,
                )

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return f"命令执行超时（超过 {timeout} 秒）"

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        output = (
            f"exit_code: {process.returncode}\n"
            f"stdout:\n{stdout or '(无输出)'}\n"
            f"stderr:\n{stderr or '(无输出)'}"
        )
        return _truncate_output(output, max_output_chars)
