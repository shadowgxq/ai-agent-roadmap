import subprocess
from pathlib import Path

from src.execution.repository import Repository


def init_repository(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "test"], cwd=path, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    (path / "README.md").write_text("repository\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"], cwd=path, check=True
    )


def test_repository_workspace_checks_out_and_cleans(tmp_path: Path):
    init_repository(tmp_path)
    repository = Repository.discover(tmp_path)
    original_head = repository.head_sha

    with repository.open_workspace() as workspace:
        assert workspace.root != repository.root
        assert (workspace.root / "README.md").read_text() == "repository\n"
        assert Repository.discover(workspace.root).head_sha == original_head
        (workspace.root / "agent-change.txt").write_text("temporary")
        temporary_root = workspace.root

    assert not temporary_root.exists()
    assert not (tmp_path / "agent-change.txt").exists()
