"""组装并运行一次 Coding Agent。"""

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
from .config import AgentSettings
from .context import Context
from .cost import estimate_cost
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
) -> tuple[ChatCompletion, RunStats]:
    """组装依赖并在指定目录运行一次 Coding Agent。"""
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise NotADirectoryError(f"工作目录不存在或不是目录: {workdir}")
    selected_model = model if model is not None else settings.model
    trace = AgentTrace(
        run_id=run_id or uuid4().hex,
        agent_id="main",
        role="main",
    )
    main_stats = RunStats()

    registry = ToolRegistry()
    register_fs_tools(registry, workdir)
    register_search_tools(registry, workdir)
    register_shell_tools(
        registry,
        workdir,
        max_output_chars=settings.max_tool_output_chars,
    )

    context = Context()
    context.append_user(build_task_message(task, workdir))
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
            )
        return await run(
            client,
            context,
            registry,
            model=selected_model,
            system_prompt=build_system_prompt(),
            max_turns=(
                max_turns
                if max_turns is not None
                else settings.max_turns
            ),
            max_tokens=max_tokens,
            cost_estimator=lambda stats: estimate_cost(stats, settings),
            max_cost_usd=max_cost_usd,
            stats=main_stats,
            trace=trace,
        )
