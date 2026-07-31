"""组装并运行一次 Coding Agent。"""

import asyncio
from pathlib import Path
from uuid import uuid4

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from ..tools import (
    ToolRegistry,
    register_fs_tools,
    register_search_tools,
    register_shell_tools,
    register_subagent_tool,
)
from .checkpoint import (
    DEFAULT_RUNS_DIR,
    Checkpoint,
    CheckpointStatus,
    RunStatsSnapshot,
    save_checkpoint,
)
from .config import AgentSettings
from .context import Context
from .cost import estimate_cost
from .git_snapshot import ensure_start_snapshot, get_head_sha
from .loop import AgentTrace, RunStats, run
from .prompts import build_system_prompt, build_task_message


async def run_coding_agent(
    task: str,
    workdir: Path,
    settings: AgentSettings,
    *,
    model: str | None = None,
    max_turns: int | None = None,
    max_tokens: int = 3000,
    max_cost_usd: float | None = None,
    run_id: str | None = None,
    enable_subagent: bool = True,
    context: Context | None = None,
    stats: RunStats | None = None,
    start_turn: int = 0,
    checkpoint_enabled: bool = False,
    runs_dir: Path = DEFAULT_RUNS_DIR,
    start_sha: str | None = None,
) -> tuple[ChatCompletion, RunStats]:
    """组装依赖并在指定目录运行一次 Coding Agent。"""
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise NotADirectoryError(f"工作目录不存在或不是目录: {workdir}")
    selected_model = model if model is not None else settings.model
    selected_max_turns = (
        max_turns if max_turns is not None else settings.max_turns
    )
    selected_run_id = run_id or uuid4().hex
    selected_start_sha = start_sha
    if selected_start_sha is None:
        selected_start_sha = (
            ensure_start_snapshot(workdir)
            if checkpoint_enabled
            else get_head_sha(workdir)
        )
    trace = AgentTrace(
        run_id=selected_run_id,
        agent_id="main",
        role="main",
    )
    main_stats = stats if stats is not None else RunStats()

    registry = ToolRegistry()
    register_fs_tools(registry, workdir)
    register_search_tools(registry, workdir)
    register_shell_tools(
        registry,
        workdir,
        max_output_chars=settings.max_tool_output_chars,
    )

    if context is None:
        context = Context()
        context.append_user(build_task_message(task, workdir))
    else:
        context.assert_paired()

    def persist_checkpoint(
        current_context: Context,
        current_stats: RunStats,
        turn: int,
        status: CheckpointStatus,
    ) -> None:
        """在完整轮次边界保存可恢复状态。"""
        total_cost = estimate_cost(current_stats, settings)
        save_checkpoint(
            Checkpoint(
                run_id=selected_run_id,
                task=task,
                messages=current_context.messages,
                turn=turn,
                stats=RunStatsSnapshot.from_stats(current_stats),
                total_cost_usd=total_cost,
                workdir=str(workdir),
                model=selected_model,
                max_turns=selected_max_turns,
                max_tokens=max_tokens,
                max_cost_usd=max_cost_usd,
                enable_subagent=enable_subagent,
                status=status,
                start_sha=selected_start_sha,
            ),
            runs_dir=runs_dir,
        )

    if checkpoint_enabled and start_turn == 0:
        persist_checkpoint(context, main_stats, 0, "running")

    def persist_failure_checkpoint(status: CheckpointStatus) -> None:
        """仅在消息完整配对时，记录可安全恢复的异常状态。"""
        try:
            context.assert_paired()
        except RuntimeError:
            # 工具调用尚未得到全部结果；保留上一份完整轮次的 checkpoint。
            return
        persist_checkpoint(context, main_stats, main_stats.turns, status)

    try:
        async with AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=0,
        ) as client:
            if enable_subagent:
                register_subagent_tool(
                    registry,
                    client=client,
                    workdir=workdir,
                    model=selected_model,
                    parent_trace=trace,
                    parent_stats=main_stats,
                    prompt_cache=settings.prompt_cache_config,
                )
            return await run(
                client,
                context,
                registry,
                model=selected_model,
                system_prompt=build_system_prompt(),
                max_turns=selected_max_turns,
                max_tokens=max_tokens,
                cost_estimator=lambda stats: estimate_cost(stats, settings),
                max_cost_usd=max_cost_usd,
                prompt_cache=settings.prompt_cache_config,
                stats=main_stats,
                trace=trace,
                start_turn=start_turn,
                checkpoint_callback=(
                    persist_checkpoint if checkpoint_enabled else None
                ),
            )
    except (asyncio.CancelledError, KeyboardInterrupt):
        if checkpoint_enabled:
            persist_failure_checkpoint("interrupted")
        raise
    except Exception:
        if checkpoint_enabled:
            persist_failure_checkpoint("failed")
        raise
