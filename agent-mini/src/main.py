"""使用 run_shell 演示异步命令执行流程。"""

import asyncio
from typing import Any

from anthropic import AsyncAnthropic


if __package__:
    from .agent.config import AgentSettings, PROJECT_ROOT
    from .agent.context import Context
    from .agent.loop import run
    from .agent.prompts import build_system_prompt
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
    from agent.prompts import build_system_prompt
    from tools import (
        register_fs_tools,
        register_search_tools,
        register_shell_tools,
        registry,
    )


def extract_text(message: Any) -> str:
    """提取响应中所有 text block 的文本。"""
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


async def main() -> None:
    """创建 Agent 依赖并运行 Shell 命令任务。"""
    settings = AgentSettings()
    register_fs_tools(registry, PROJECT_ROOT)
    register_search_tools(registry, PROJECT_ROOT)
    register_shell_tools(registry, PROJECT_ROOT)
    context = Context()
    context.append_user(
        "分析下当前的入口文件是哪个"
    )

    system_prompt = build_system_prompt(PROJECT_ROOT)

    async with AsyncAnthropic(
        api_key=settings.api_key,
        base_url=settings.base_url,
    ) as client:
        final_response = await run(
            client,
            context,
            registry,
            model=settings.model,
            system_prompt=system_prompt,
            max_turns=settings.max_turns,
            max_tokens=3000,
        )

    print(f"最终 stop_reason: {final_response.stop_reason}")
    print(f"最终回答: {extract_text(final_response)}")


if __name__ == "__main__":
    asyncio.run(main())
