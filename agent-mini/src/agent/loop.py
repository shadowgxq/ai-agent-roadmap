from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message

from .context import Context


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
