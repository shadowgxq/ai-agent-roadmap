"""发送一次最小 Messages API 请求。"""

import asyncio
from typing import Any

from anthropic import AsyncAnthropic

from .agent.config import AgentSettings


def extract_text(message: Any) -> str:
    """提取响应中所有 text block 的文本。"""
    return "".join(
        block.text for block in message.content if block.type == "text"
    )


async def main() -> None:
    """加载配置，发送请求并打印关键响应字段。"""
    settings = AgentSettings()
    client = AsyncAnthropic(
        api_key=settings.api_key,
        base_url=settings.base_url,
    )

    response = await client.messages.create(
        model=settings.model,
        max_tokens=128,
        messages=[
            {
                "role": "user",
                "content": "请用一句话解释什么是 AI Agent。",
            }
        ],
    )

    print(extract_text(response))
    print(f"stop_reason: {response.stop_reason}")
    print(f"input_tokens: {response.usage.input_tokens}")
    print(f"output_tokens: {response.usage.output_tokens}")


if __name__ == "__main__":
    asyncio.run(main())
