"""连接模型、消息上下文和工具执行的 Agent 核心流程组件。"""

from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message

from .context import Context


class MaxTurnsExceeded(RuntimeError):
    """Agent 在限定轮数内没有完成任务。"""


async def run(
    client: AsyncAnthropic,
    context: Context,
    registry: Any,
    *,
    model: str,
    system_prompt: str,
    max_turns: int = 10,
    max_tokens: int = 300,
) -> Message:
    """运行 Agent，直到模型结束或达到最大轮数。"""
    tools = registry.schemas()
    for turn in range(1, max_turns + 1):
        response = await call_llm(
            client,
            context,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            max_tokens=max_tokens,
        )

        context.append_assistant(assistant_content(response))

        if response.stop_reason != "tool_use":
            return response

        tool_results = await execute_tools(response, registry)
        context.append_tool_results(tool_results)
        context.assert_paired()

    raise MaxTurnsExceeded(
        f"Agent 达到最大轮数限制: {max_turns}"
    )


async def call_llm(
    client: AsyncAnthropic,
    context: Context,
    *,
    model: str,
    system_prompt: str,
    tools: list[dict[str, Any]],
    max_tokens: int = 300,
) -> Message:
    """发起一次非流式模型请求并返回原始响应。

    这里只负责调用 API，不修改 Context、不执行工具，也不判断任务是否结束；
    这些控制逻辑由上层的 run() 统一编排。
    """
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=context.messages,
        tools=tools,
    )
    return response


def assistant_content(message: Message) -> list[dict[str, Any]]:
    """把 SDK content blocks 转成 Context 保存的标准字典。

    必须保留完整的 assistant content，包括 tool_use、thinking 及其签名，
    因为后续模型请求需要重放这条完整消息。
    """
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


async def execute_tools(
    message: Message,
    registry: Any,
) -> list[dict[str, Any]]:
    """按出现顺序执行所有 tool_use，并生成对应的 tool_result。

    text、thinking 等非工具 block 会被忽略。注册表会把工具异常转换为
    is_error=True 的执行结果，因此即使执行失败也能与 tool_use.id 正确配对。
    """
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
