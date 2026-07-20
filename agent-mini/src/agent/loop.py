from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message

from .context import Context


# 调用大模型的基础函数
async def call_llm(
    client: AsyncAnthropic,
    context: Context,
    *,
    model: str,
    system_prompt: str,
    tools: list[dict[str, Any]],
    max_tokens: int = 300,
) -> Message:
    """调用 LLM 生成响应。"""
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=context.messages,
        tools=tools,
    )
    return response


def assistant_content(message: Message) -> list[dict[str, Any]]:
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


# 模型返回的 tool_use 转成 tool_result


async def execute_tools(
    message: Message,
    registry: Any,
) -> list[dict[str, Any]]:
    tool_uses = [
        block
        for block in message.content
        if block.type == "tool_use"
    ]
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
    return tool_results
