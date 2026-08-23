import asyncio
from pathlib import Path

from src.execution.executor import DockerExecutor, LocalExecutor
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


def test_docker_executor_builds_isolated_command(tmp_path: Path):
    executor = DockerExecutor(
        LocalWorkspace(tmp_path),
        image="agent-mini-sandbox:test",
        cpu_limit=0.5,
        memory_limit="256m",
        pids_limit=32,
    )
    command = executor.build_command("python -V")

    assert command[:4] == ["docker", "run", "--rm", "--init"]
    assert ["--network", "none"] == command[4:6]
    assert "--read-only" in command
    assert "--pids-limit" in command
    assert "--user" in command
    assert "10001:10001" in command
    assert any(
        item.startswith("type=bind,") and "target=/workspace" in item
        for item in command
    )
    assert "/etc" not in " ".join(command)
