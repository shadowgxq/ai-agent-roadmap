import asyncio
from pathlib import Path

from src.execution.executor import LocalExecutor
from src.execution.workspace import LocalWorkspace
from src.tools.policy import Policy


def test_local_executor_runs_inside_workspace(tmp_path: Path):
    executor = LocalExecutor(LocalWorkspace(tmp_path))
    result = asyncio.run(executor.execute("python -c \"print('ok')\""))

    assert result.status == "completed"
    assert result.is_error is False
    assert "ok" in result.content


def test_local_executor_applies_policy_before_process(tmp_path: Path):
    executor = LocalExecutor(
        LocalWorkspace(tmp_path),
        policy=Policy(denied_commands={"echo"}),
    )
    result = asyncio.run(executor.execute("echo should-not-run"))

    assert result.status == "denied"
    assert result.is_error is True
    assert not (tmp_path / "output.txt").exists()


def test_local_executor_can_wait_for_confirmation(tmp_path: Path):
    executor = LocalExecutor(
        LocalWorkspace(tmp_path),
        on_confirm=lambda command, reason: False,
    )
    result = asyncio.run(executor.execute("rm missing.txt"))

    assert result.status == "denied"
    assert result.reason == "用户拒绝执行命令"
