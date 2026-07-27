"""组装并运行一次 Coding Agent。"""

from pathlib import Path

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from ..tools import (
    ToolRegistry,
    register_fs_tools,
    register_search_tools,
    register_shell_tools,
)
from .config import AgentSettings
from .context import Context
from .loop import RunStats, run
from .prompts import build_system_prompt, build_task_message


async def run_coding_agent(
    task: str,
    workdir: Path,
    settings: AgentSettings,
    *,
    model: str | None = None,
    max_turns: int | None = None,
    max_tokens: int = 3000,
) -> tuple[ChatCompletion, RunStats]:
    """组装依赖并在指定目录运行一次 Coding Agent。"""
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise NotADirectoryError(f"工作目录不存在或不是目录: {workdir}")

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
    ) as client:
        return await run(
            client,
            context,
            registry,
            model=model if model is not None else settings.model,
            system_prompt=build_system_prompt(),
            max_turns=(
                max_turns
                if max_turns is not None
                else settings.max_turns
            ),
            max_tokens=max_tokens,
        )
