"""使用 read_file 和 edit_file 演示精确修改验证流程。"""

import asyncio
from typing import Any

from anthropic import AsyncAnthropic


if __package__:
    from .agent.config import AgentSettings, PROJECT_ROOT
    from .agent.context import Context
    from .agent.loop import run
    from .tools import (
        register_fs_tools,
        register_search_tools,
        registry
    )
else:
    from agent.config import AgentSettings, PROJECT_ROOT
    from agent.context import Context
    from agent.loop import run
    from tools import (
        register_fs_tools,
        register_search_tools,
        registry
    )


def extract_text(message: Any) -> str:
    """提取响应中所有 text block 的文本。"""
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


async def main() -> None:
    """创建 Agent 依赖并运行文件精确修改任务。"""
    settings = AgentSettings()
    register_fs_tools(registry, PROJECT_ROOT)
    register_search_tools(registry, PROJECT_ROOT)
    context = Context()
    context.append_user(
        "请先使用 grep 在 src 目录中查找 `async def run` 的定义，"
        "再使用 read_file 阅读对应文件，并说明 run() 的主要流程。"
    )

    system_prompt = (
        "定位代码时必须先使用 grep，找到准确文件后再使用 read_file；"
        "不能根据文件名猜测代码内容。"
    )

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
