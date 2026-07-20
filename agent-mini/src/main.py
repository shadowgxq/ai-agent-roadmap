"""W02 复习入口：演示一次固定的 Messages API Tool Use 回路。"""

import asyncio
from typing import Any

from anthropic import AsyncAnthropic


if __package__:
    # `python -m src.main` 使用包内相对导入。
    from .agent.config import AgentSettings
    from .agent.context import Context
    from .agent.loop import assistant_content, execute_tools
    from .tools import registry
else:
    # VS Code 的“运行 Python 文件”会直接执行当前文件。
    from agent.config import AgentSettings
    from agent.context import Context
    from agent.loop import assistant_content, execute_tools
    from tools import registry


def extract_text(message: Any) -> str:
    """提取响应中所有 text block 的文本。"""
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


async def main() -> None:
    """执行一次模型调用、工具回填和最终回答，不包含通用 Agent 循环。"""
    settings = AgentSettings()
    context = Context()
    context.append_user("北京今天天气怎么样？请使用工具查询。")

    system_prompt = "用户询问天气时必须调用工具，不能猜测工具结果。"

    async with AsyncAnthropic(
        api_key=settings.api_key,
        base_url=settings.base_url,
    ) as client:
        print("===工具", registry.schemas())
        # 第一次请求要求模型选择工具，并返回 assistant(tool_use)。
        first_response = await client.messages.create(
            model=settings.model,
            max_tokens=300,
            system=system_prompt,
            messages=context.messages,
            tools=registry.schemas(),
        )

        # 工具结果之前必须先保存触发它的完整 assistant 消息。
        context.append_assistant(assistant_content(first_response))

        if first_response.stop_reason != "tool_use":
            raise RuntimeError("模型没有返回预期的 tool_use")
        tool_results = await execute_tools(first_response, registry)
        context.append_tool_results(tool_results)
        context.assert_paired()
        # 第二次请求让模型读取 tool_result 并组织最终自然语言回答。
        final_response = await client.messages.create(
            model=settings.model,
            max_tokens=300,
            system=system_prompt,
            messages=context.messages,
            tools=registry.schemas(),
        )
        context.append_assistant(assistant_content(final_response))

        print(f"第二次响应 stop_reason: {final_response.stop_reason}")
        print(f"最终回答: {extract_text(final_response)}")


if __name__ == "__main__":
    asyncio.run(main())
