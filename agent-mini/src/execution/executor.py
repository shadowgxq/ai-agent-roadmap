"""命令执行器抽象。

Executor 负责命令运行位置、超时、环境和执行结果；工具层只负责把它
适配成模型可调用的 ``run_shell`` 工具。这样 LocalExecutor 可以替换为
DockerExecutor，而 Agent Loop 不需要知道具体执行位置。
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Literal

from ..agent.config import ConfirmCallback
from .workspace import Workspace

if TYPE_CHECKING:
    from ..tools.policy import Policy


ExecutionStatus = Literal[
    "completed",
    "failed",
    "denied",
    "waiting_confirmation",
    "timeout",
    "cancelled",
]


@dataclass(frozen=True)
class ExecutionResult:
    """一次命令执行的统一结果。"""

    command: str
    content: str
    status: ExecutionStatus
    is_error: bool
    exit_code: int | None = None
    duration_ms: int = 0
    reason: str | None = None


class Executor:
    """Executor 的最小异步协议。"""

    async def execute(self, command: str) -> ExecutionResult:
        """执行一条命令并返回结构化结果。"""
        raise NotImplementedError


def truncate_output(output: str, max_chars: int) -> str:
    """输出过长时保留头尾，避免工具结果撑爆模型上下文。"""
    if len(output) <= max_chars:
        return output

    marker = "\n...(中间内容已截断)...\n"
    if max_chars <= len(marker):
        return output[:max_chars]

    remaining = max_chars - len(marker)
    head_chars = remaining // 2
    tail_chars = remaining - head_chars
    return f"{output[:head_chars]}{marker}{output[-tail_chars:]}"


class LocalExecutor(Executor):
    """在 Workspace 根目录中执行命令的本地实现。"""

    def __init__(
        self,
        workspace: Workspace,
        *,
        timeout: float = 30.0,
        max_output_chars: int = 10_000,
        policy: Policy | None = None,
        on_confirm: ConfirmCallback | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if max_output_chars <= 0:
            raise ValueError("max_output_chars 必须大于 0")
        self.workspace = workspace
        self.timeout = timeout
        self.max_output_chars = max_output_chars
        if policy is None:
            from ..tools.policy import Policy

            policy = Policy()
        self.policy = policy
        self.on_confirm = on_confirm

    @staticmethod
    def _environment() -> dict[str, str]:
        """为本地子进程补齐 Agent 当前 Python 和用户 bin 路径。"""
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
        return environment

    async def execute(self, command: str) -> ExecutionResult:
        """先过策略，再在 Workspace 根目录启动本地 Shell。"""
        started_at = perf_counter()
        raw_command = command.strip()
        if not raw_command:
            return ExecutionResult(
                command=command,
                content="命令不能为空",
                status="denied",
                is_error=True,
            )

        decision = self.policy.evaluate(raw_command)
        from ..tools.policy import PolicyAction

        if decision.action is PolicyAction.DENY:
            return self._policy_result(
                raw_command,
                status="denied",
                reason=decision.reason,
                started_at=started_at,
            )

        if decision.action is PolicyAction.CONFIRM:
            if self.on_confirm is None:
                return self._policy_result(
                    raw_command,
                    status="waiting_confirmation",
                    reason=decision.reason,
                    started_at=started_at,
                )

            approved = self.on_confirm(raw_command, decision.reason)
            if inspect.isawaitable(approved):
                approved = await approved
            if not approved:
                return self._policy_result(
                    raw_command,
                    status="denied",
                    reason="用户拒绝执行命令",
                    started_at=started_at,
                )

        try:
            process = await asyncio.create_subprocess_shell(
                raw_command,
                cwd=self.workspace.root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._environment(),
            )
        except OSError as exc:
            return ExecutionResult(
                command=raw_command,
                content=f"命令启动失败: {type(exc).__name__}: {exc}",
                status="failed",
                is_error=True,
                duration_ms=self._duration_ms(started_at),
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return ExecutionResult(
                command=raw_command,
                content=f"命令执行超时（超过 {self.timeout:g} 秒）",
                status="timeout",
                is_error=True,
                duration_ms=self._duration_ms(started_at),
            )
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.communicate()
            raise

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        exit_code = process.returncode
        output = (
            f"exit_code: {exit_code}\n"
            f"stdout:\n{stdout or '(无输出)'}\n"
            f"stderr:\n{stderr or '(无输出)'}"
        )
        return ExecutionResult(
            command=raw_command,
            content=truncate_output(output, self.max_output_chars),
            status="completed" if exit_code == 0 else "failed",
            is_error=exit_code != 0,
            exit_code=exit_code,
            duration_ms=self._duration_ms(started_at),
        )

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return round((perf_counter() - started_at) * 1000)

    def _policy_result(
        self,
        command: str,
        *,
        status: Literal["denied", "waiting_confirmation"],
        reason: str,
        started_at: float,
    ) -> ExecutionResult:
        label = (
            "命令拒绝，未执行"
            if status == "denied"
            else "命令需要确认，暂未执行"
        )
        return ExecutionResult(
            command=command,
            content=f"{label}: {command}\n原因: {reason}",
            status=status,
            is_error=True,
            duration_ms=self._duration_ms(started_at),
            reason=reason,
        )


__all__ = [
    "ExecutionResult",
    "ExecutionStatus",
    "Executor",
    "LocalExecutor",
    "truncate_output",
]
