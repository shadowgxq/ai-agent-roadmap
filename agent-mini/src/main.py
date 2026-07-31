"""使用 run_shell 演示异步命令执行流程。"""

import asyncio
from typing import Any

from openai import AsyncOpenAI


if __package__:
    from .agent.config import AgentSettings, PROJECT_ROOT
    from .agent.context import Context
    from .agent.loop import run
    from .agent.prompts import build_system_prompt, build_task_message
    from .agent.logging_config import configure_logging, get_logger
    from .tools import (
        register_fs_tools,
        register_search_tools,
        register_shell_tools,
        registry,
    )
else:
    from agent.config import AgentSettings, PROJECT_ROOT
    from agent.context import Context
    from agent.loop import run
    from agent.prompts import build_system_prompt, build_task_message
    from agent.logging_config import configure_logging, get_logger
    from tools import (
        register_fs_tools,
        register_search_tools,
        register_shell_tools,
        registry,
    )


logger = get_logger("main")


def extract_text(message: Any) -> str:
    """提取 Chat Completions 响应中的 assistant 文本。"""
    return message.choices[0].message.content or ""


async def main() -> None:
    """创建 Agent 依赖并运行 Shell 命令任务。"""
    settings = AgentSettings()
    log_file = configure_logging(settings.log_file)
    logger.info(
        "详细日志: %s",
        log_file,
        extra={
            "event": "run.started",
            "data": {
                "workdir": str(PROJECT_ROOT),
                "log_file": str(log_file),
                "model": settings.model,
                "max_turns": settings.max_turns,
            },
        },
    )
    register_fs_tools(registry, PROJECT_ROOT)
    register_search_tools(registry, PROJECT_ROOT)
    register_shell_tools(registry, PROJECT_ROOT)
    context = Context()
    context.append_user(
        build_task_message("分析下当前的入口文件是哪个", PROJECT_ROOT)
    )

    system_prompt = build_system_prompt()

    async with AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        max_retries=0,
    ) as client:
        final_response, stats = await run(
            client,
            context,
            registry,
            model=settings.model,
            system_prompt=system_prompt,
            max_turns=settings.max_turns,
            max_tokens=3000,
            prompt_cache=settings.prompt_cache_config,
        )

    answer = extract_text(final_response)
    logger.info(
        "最终回答: %s",
        answer,
        extra={
            "event": "run.completed",
            "data": {
                "turns": stats.turns,
                "input_tokens": stats.input_tokens,
                "cache_read_input_tokens": stats.cache_read_input_tokens,
                "cache_creation_input_tokens": (
                    stats.cache_creation_input_tokens
                ),
                "output_tokens": stats.output_tokens,
                "total_tokens": (
                    stats.input_tokens
                    + stats.cache_read_input_tokens
                    + stats.cache_creation_input_tokens
                    + stats.output_tokens
                ),
                "finish_reason": final_response.choices[0].finish_reason,
                "answer": answer,
            },
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
