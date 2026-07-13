from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from anthropic import AsyncAnthropic

from agent_sdk import (
    extract_assistant_blocks,
    extract_text,
    get_async_client,
    load_config,
)

if __package__:
    from .registry import ToolExecutionResult, ToolRegistry, registry
else:
    # 直接执行 python tools/loop.py 时，没有包上下文，改用同目录导入。
    from registry import ToolExecutionResult, ToolRegistry, registry


class MaxTurnsExceeded(RuntimeError):
    """模型连续请求工具超过允许的最大轮数。"""


def _summarize(value: Any, limit: int = 500) -> str:
    """把工具结果转换成适合终端打印的短摘要。"""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)

    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def assert_paired(messages: list[dict[str, Any]]) -> None:
    """检查每个 tool_use 是否都有对应的 tool_result。"""
    pending_ids: dict[str, int] = {}

    for message_index, message in enumerate(messages):
        role = message.get("role")
        content = message.get("content", [])
        blocks = content if isinstance(content, list) else []

        if role == "assistant":
            if pending_ids:
                raise RuntimeError("assistant tool_use 后缺少对应的 tool_result")

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue

                tool_use_id = block.get("id")
                if not tool_use_id:
                    raise RuntimeError("tool_use 缺少 id")
                if tool_use_id in pending_ids:
                    raise RuntimeError(f"tool_use_id 重复: {tool_use_id}")
                pending_ids[tool_use_id] = message_index

        if role != "user":
            continue

        tool_result_blocks = [
            block
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "tool_result"
        ]
        if not tool_result_blocks:
            if pending_ids:
                raise RuntimeError("tool_use 后出现普通 user 消息")
            continue

        if not pending_ids:
            raise RuntimeError("发现 tool_result，但没有等待中的 tool_use")

        for block in tool_result_blocks:
            tool_use_id = block.get("tool_use_id")
            if tool_use_id not in pending_ids:
                raise RuntimeError(
                    f"tool_result 没有匹配的 tool_use: {tool_use_id}"
                )
            del pending_ids[tool_use_id]

        if pending_ids:
            raise RuntimeError("部分 tool_use 缺少 tool_result")

    if pending_ids:
        raise RuntimeError("对话结束时仍有未配对的 tool_use")


async def run_with_tools(
    messages: list[dict[str, Any]],
    registry: ToolRegistry,
    max_turns: int = 10,
    *,
    client: AsyncAnthropic,
    model: str,
    system_prompt: str | None = None,
    max_tokens: int = 1000,
) -> str:
    """执行完整的模型工具调用循环，并返回模型最终文本。"""
    if max_turns < 1:
        raise ValueError("max_turns 必须大于等于 1")

    for turn in range(1, max_turns + 1):
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": registry.schemas(),
            "max_tokens": max_tokens,
        }
        if system_prompt is not None:
            request["system"] = system_prompt

        response = await client.messages.create(**request)
        assistant_blocks = extract_assistant_blocks(response)
        messages.append(
            {
                "role": "assistant",
                "content": assistant_blocks,
            }
        )

        model_text = extract_text(response)
        print(f"\n=== Tool Loop Round {turn} ===")
        print(f"stop_reason: {response.stop_reason}")
        if model_text:
            print(f"model_text: {model_text}")

        # 没有 tool_use 时，说明模型已经认为任务完成。
        if response.stop_reason != "tool_use":
            assert_paired(messages)
            return model_text

        tool_use_blocks = [
            block
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
        ]
        if not tool_use_blocks:
            raise RuntimeError(
                "stop_reason 是 tool_use，但响应中没有 tool_use block"
            )

        async def execute_one(block: Any) -> dict[str, Any]:
            """执行一个工具调用，并转换成 tool_result 消息块。"""
            started_at = time.perf_counter()
            print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"tool_start: {block.name} {block.input}"
            )

            try:
                execution = await registry.execute_with_status(
                    block.name,
                    block.input,
                )
            except Exception as exc:
                # 兜住 registry 之外的异常，确保本轮仍能回传结果。
                execution = ToolExecutionResult(
                    content=(
                        f"工具 {block.name} 执行失败: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    is_error=True,
                )

            elapsed = time.perf_counter() - started_at
            print(
                f"[{time.strftime('%H:%M:%S')}] "
                f"tool_end: {block.name} elapsed={elapsed:.2f}s "
                f"is_error={execution.is_error}"
            )
            print(f"tool_result: {_summarize(execution.content)}")

            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": execution.content,
                "is_error": execution.is_error,
            }

        # gather 会并发执行工具，返回顺序仍与 tool_use_blocks 一致。
        tool_results = await asyncio.gather(
            *(execute_one(block) for block in tool_use_blocks)
        )

        # 同一轮 assistant 产生的所有结果，必须放在同一条 user 消息中。
        messages.append(
            {
                "role": "user",
                "content": tool_results,
            }
        )
        assert_paired(messages)
    raise MaxTurnsExceeded(f"工具调用超过最大轮数: {max_turns}")


async def main() -> None:
    """创建客户端并运行一个包含天气查询和计算的多步示例。"""
    config = load_config()
    user_message = (
        " ".join(sys.argv[1:]).strip()
        or "先获取当前的时间，先查北京天气，再帮我计算 (3+5)*12"
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]

    async with get_async_client(config) as client:
        answer = await run_with_tools(
            messages,
            registry,
            client=client,
            model=config.model,
            system_prompt=(
                "你是一个会调用工具的中文助理。"
                "遇到天气问题必须调用 get_weather，"
                "需要计算时必须调用 calculate，不要猜测工具结果。"
            ),
            max_turns=10,
        )

    print("\n=== Final Answer ===")
    print(answer)


__all__ = [
    "MaxTurnsExceeded",
    "assert_paired",
    "main",
    "run_with_tools",
]


if __name__ == "__main__":
    asyncio.run(main())
