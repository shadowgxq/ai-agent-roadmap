"""读取 Coding Agent 工作目录的 Git 起点信息。"""

import subprocess
from pathlib import Path


class GitSnapshotError(RuntimeError):
    """Git 快照或回滚无法安全完成。"""


def _run_git(
    workdir: Path,
    *arguments: str,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    """在指定目录执行 Git 命令，不经过 shell。"""
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitSnapshotError("未找到 git，无法创建可回滚快照") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitSnapshotError("git 命令超时，未完成快照操作") from exc


def get_repo_root(workdir: Path) -> Path | None:
    """返回工作目录所属 Git 根目录；不是仓库时返回 None。"""
    result = _run_git(workdir, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def _scope_path(repo_root: Path, workdir: Path) -> str:
    """生成相对仓库根目录的 pathspec，限制操作范围。"""
    relative = workdir.resolve().relative_to(repo_root)
    return relative.as_posix() or "."


def _commit_snapshot(repo_root: Path, scope: str) -> None:
    """把指定范围提交为 Agent 任务起点。"""
    add_result = _run_git(repo_root, "add", "-A", "--", scope)
    if add_result.returncode != 0:
        raise GitSnapshotError(
            f"无法暂存 Git 快照: {add_result.stderr.strip()}"
        )

    commit_result = _run_git(
        repo_root,
        "-c",
        "user.name=agent-mini",
        "-c",
        "user.email=agent-mini@localhost",
        "commit",
        "--only",
        "--allow-empty",
        "-m",
        "agent-start",
        "--",
        scope,
    )
    if commit_result.returncode != 0:
        raise GitSnapshotError(
            f"无法创建 Git 起点提交: {commit_result.stderr.strip()}"
        )


def ensure_start_snapshot(workdir: Path) -> str:
    """初始化或提交工作区，并返回任务起点 commit SHA。"""
    workdir = workdir.resolve()
    repo_root = get_repo_root(workdir)
    if repo_root is None:
        init_result = _run_git(workdir, "init")
        if init_result.returncode != 0:
            raise GitSnapshotError(
                f"无法初始化 Git 仓库: {init_result.stderr.strip()}"
            )
        repo_root = get_repo_root(workdir)
        if repo_root is None:
            raise GitSnapshotError("Git 初始化后无法确定仓库根目录")

    scope = _scope_path(repo_root, workdir)
    status = _run_git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        scope,
    )
    if status.returncode != 0:
        raise GitSnapshotError(
            f"无法读取 Git 工作区状态: {status.stderr.strip()}"
        )

    head = get_head_sha(workdir)
    if head is None or status.stdout.strip():
        _commit_snapshot(repo_root, scope)
        head = get_head_sha(workdir)

    if head is None:
        raise GitSnapshotError("Git 起点提交创建后仍无法读取 HEAD")
    return head


def rollback_to_sha(workdir: Path, start_sha: str) -> None:
    """将工作目录恢复到起点，并清理 Agent 新增的未跟踪文件。"""
    if not start_sha:
        raise GitSnapshotError("Checkpoint 没有可用的 start_sha")

    workdir = workdir.resolve()
    repo_root = get_repo_root(workdir)
    if repo_root is None:
        raise GitSnapshotError(f"工作目录不是 Git 仓库: {workdir}")
    scope = _scope_path(repo_root, workdir)

    verify = _run_git(repo_root, "cat-file", "-e", f"{start_sha}^{{commit}}")
    if verify.returncode != 0:
        raise GitSnapshotError(f"找不到有效的起点提交: {start_sha}")

    if scope == ".":
        restore = _run_git(repo_root, "reset", "--hard", start_sha)
    else:
        # 子目录任务只恢复自己的 pathspec，不能重置父仓库的其他修改。
        restore = _run_git(
            repo_root,
            "restore",
            "--source",
            start_sha,
            "--staged",
            "--worktree",
            "--",
            scope,
        )
    if restore.returncode != 0:
        raise GitSnapshotError(f"恢复 Git 文件失败: {restore.stderr.strip()}")

    clean = _run_git(repo_root, "clean", "-fd", "--", scope)
    if clean.returncode != 0:
        raise GitSnapshotError(f"清理 Agent 新文件失败: {clean.stderr.strip()}")


def get_head_sha(workdir: Path) -> str | None:
    """返回工作目录当前 HEAD；目录不是 Git 仓库时返回 None。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
