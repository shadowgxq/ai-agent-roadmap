"""演示一次完整的 Messages API Tool Use 回路。"""

import asyncio
from typing import Any

from anthropic import AsyncAnthropic

if __package__:
    # `python -m src.main` 使用包内相对导入。
    from .agent.config import AgentSettings
    from .agent.context import Context
    from .tools import registry
else:
    # VS Code 的“运行 Python 文件”会直接执行当前文件。
    from agent.config import AgentSettings
    from agent.context import Context
    from tools import registry


def extract_text(message: Any) -> str:
    """提取响应中所有 text block 的文本。"""
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


def assistant_content(message: Any) -> list[dict[str, Any]]:
    """把响应 content 转换成下一次请求可发送的消息块。"""
    content: list[dict[str, Any]] = []
    for block in message.content:
        if block.type == "text":
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
        elif block.type == "thinking":
            content.append(
                {
                    "type": "thinking",
                    "thinking": block.thinking,
                    "signature": block.signature,
                }
            )
        elif block.type == "redacted_thinking":
            content.append(
                {
                    "type": "redacted_thinking",
                    "data": block.data,
                }
            )
        else:
            raise RuntimeError(f"暂不支持的 content block: {block.type}")
    return content


async def main() -> None:
    """执行一次 tool_use -> tool_result -> final answer 流程。"""
    settings = AgentSettings()
    context = Context()
    context.append_user("北京今天天气怎么样？请使用工具查询。")

    system_prompt = "用户询问天气时必须调用工具，不能猜测工具结果。"

    async with AsyncAnthropic(
        api_key=settings.api_key,
        base_url=settings.base_url,
    ) as client:
        print("===工具", registry.schemas())
        first_response = await client.messages.create(
            model=settings.model,
            max_tokens=300,
            system=system_prompt,
            messages=context.messages,
            tools=registry.schemas(),
        )

        context.append_assistant(assistant_content(first_response))

        tool_uses = [
            block
            for block in first_response.content
            if block.type == "tool_use"
        ]
        if first_response.stop_reason != "tool_use" or not tool_uses:
            raise RuntimeError("模型没有返回预期的 tool_use")

        tool_results: list[dict[str, Any]] = []
        for tool_use in tool_uses:
            print(f"调用工具: {tool_use.name} {tool_use.input}")
            execution = await registry.execute_with_status(
                tool_use.name,
                tool_use.input,
            )
            print(f"工具结果: {execution.content}")
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": execution.content,
                    "is_error": execution.is_error,
                }
            )
        context.append_tool_results(tool_results)
        context.assert_paired()
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
