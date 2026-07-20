"""使用本地 mock 工具演示完整 Agent 循环。"""

import asyncio
from typing import Any

from anthropic import AsyncAnthropic


if __package__:
    from .agent.config import AgentSettings
    from .agent.context import Context
    from .agent.loop import run
    from .tools import registry
else:
    from agent.config import AgentSettings
    from agent.context import Context
    from agent.loop import run
    from tools import registry


def extract_text(message: Any) -> str:
    """提取响应中所有 text block 的文本。"""
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


async def main() -> None:
    """创建 Agent 依赖并运行天气查询任务。"""
    settings = AgentSettings()
    context = Context()
    context.append_user("北京今天天气怎么样？请使用工具查询。")

    system_prompt = "用户询问天气时必须调用工具，不能猜测工具结果。"

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
            max_tokens=300,
        )

    print(f"最终 stop_reason: {final_response.stop_reason}")
    print(f"最终回答: {extract_text(final_response)}")


if __name__ == "__main__":
    asyncio.run(main())
