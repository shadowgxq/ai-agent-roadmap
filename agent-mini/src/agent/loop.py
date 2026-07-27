"""连接模型、消息上下文和工具执行的 Agent 核心流程组件。"""

import asyncio
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage

from .context import Context


@dataclass
class RunStats:
    """记录模型调用统计，input_tokens 不包含缓存读写的输入。"""

    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class UsageTokens:
    """Normalized token usage shared by supported provider formats."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


def _usage_value(source: Any, *names: str) -> Any:
    """Read the first available field from a dict or SDK object."""
    if source is None:
        return None

    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]

        value = getattr(source, name, None)
        if value is not None:
            return value

        extra = getattr(source, "model_extra", None)
        if isinstance(extra, dict) and name in extra:
            return extra[name]

    return None


def _token_count(value: Any) -> int:
    """Convert an optional token field to a non-negative integer."""
    if value is None:
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def extract_usage_tokens(usage: Any) -> UsageTokens:
    """Normalize OpenAI-style and Anthropic-style usage fields."""
    details = _usage_value(usage, "prompt_tokens_details")

    cache_read = _token_count(
        _usage_value(usage, "cache_read_input_tokens", "cache_read_tokens")
    )
    if cache_read == 0:
        cache_read = _token_count(
            _usage_value(
                details,
                "cache_read_input_tokens",
                "cache_read_tokens",
                "cached_tokens",
            )
        )

    cache_creation = _token_count(
        _usage_value(
            usage,
            "cache_creation_input_tokens",
            "cache_creation_tokens",
            "cache_write_input_tokens",
        )
    )
    if cache_creation == 0:
        cache_creation = _token_count(
            _usage_value(
                details,
                "cache_creation_input_tokens",
                "cache_creation_tokens",
                "cache_write_input_tokens",
            )
        )

    explicit_input = _usage_value(usage, "input_tokens")
    prompt_tokens = _token_count(_usage_value(usage, "prompt_tokens"))
    if explicit_input is not None:
        input_tokens = _token_count(explicit_input)
    else:
        # OpenAI-style prompt_tokens commonly includes cached input.
        input_tokens = max(prompt_tokens - cache_read - cache_creation, 0)

    output_tokens = _token_count(
        _usage_value(usage, "output_tokens", "completion_tokens")
    )
    return UsageTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )


class MaxTurnsExceeded(RuntimeError):
    """Agent 在限定轮数内没有完成任务。"""

    def __init__(self, max_turns: int, stats: RunStats):
        super().__init__(f"Agent 达到最大轮数限制: {max_turns}")
        self.max_turns = max_turns
        self.stats = stats


class CostLimitExceeded(RuntimeError):
    """Agent 的累计模型费用超过单任务预算。"""

    def __init__(
        self,
        max_cost_usd: float,
        actual_cost_usd: float,
        stats: RunStats,
    ):
        super().__init__(
            f"Agent 费用 ${actual_cost_usd:.6f} 超过限制 "
            f"${max_cost_usd:.6f}"
        )
        self.max_cost_usd = max_cost_usd
        self.actual_cost_usd = actual_cost_usd
        self.stats = stats


@dataclass
class ToolCallTracker:
    """检测连续重复的完全相同工具调用。"""

    max_consecutive: int = 3
    _last_signature: tuple[str, str] | None = None
    _count: int = 0

    def allow(self, name: str, input_data: Any) -> bool:
        """记录一次调用，达到连续上限后拒绝执行。"""
        signature = (
            name,
            json.dumps(input_data, sort_keys=True, default=str),
        )
        if signature == self._last_signature:
            self._count += 1
        else:
            self._last_signature = signature
            self._count = 1
        return self._count < self.max_consecutive


async def run(
    client: AsyncOpenAI,
    context: Context,
    registry: Any,
    *,
    model: str,
    system_prompt: str,
    max_turns: int = 10,
    max_tokens: int = 300,
    cost_estimator: Callable[[RunStats], float | None] | None = None,
    max_cost_usd: float | None = None,
) -> tuple[ChatCompletion, RunStats]:
    """运行 Agent，直到模型结束或达到最大轮数。"""
    if max_cost_usd is not None:
        if max_cost_usd <= 0:
            raise ValueError("max_cost_usd 必须大于 0")
        if cost_estimator is None:
            raise ValueError("设置 max_cost_usd 时必须提供 cost_estimator")

    tools = registry.schemas()
    stats = RunStats()
    tracker = ToolCallTracker()
    for turn in range(1, max_turns + 1):
        print(f"\n===== 第 {turn}/{max_turns} 轮 =====")
        response = await call_llm(
            client,
            context,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            max_tokens=max_tokens,
        )
        message = response.choices[0].message
        text = message_text(message)
        if text:
            print(f"模型文本: {text}")

        token_usage = extract_usage_tokens(response.usage)

        stats.turns += 1
        stats.input_tokens += token_usage.input_tokens
        stats.cache_read_input_tokens += token_usage.cache_read_input_tokens
        stats.cache_creation_input_tokens += (
            token_usage.cache_creation_input_tokens
        )
        stats.output_tokens += token_usage.output_tokens

        if max_cost_usd is not None and cost_estimator is not None:
            current_cost = cost_estimator(stats)
            if current_cost is None:
                raise ValueError("缺少完整的模型价格配置，无法执行费用熔断")
            if current_cost > max_cost_usd:
                raise CostLimitExceeded(
                    max_cost_usd=max_cost_usd,
                    actual_cost_usd=current_cost,
                    stats=stats,
                )

        context.append_assistant(assistant_message(message))

        if not message.tool_calls:
            return response, stats

        tool_results = await execute_tools(message, registry, tracker)
        context.append_tool_results(tool_results)
        context.assert_paired()

    raise MaxTurnsExceeded(max_turns, stats)


def message_text(message: ChatCompletionMessage) -> str:
    """提取响应中的 assistant 文本。"""
    return (message.content or "").strip()


def openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把注册表的 Anthropic 风格 schema 转成 OpenAI function schema。"""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in tools
    ]


def is_retryable_llm_error(exc: Exception) -> bool:
    """只允许网络错误、限流和服务端错误进入重试。"""
    if isinstance(exc, APIConnectionError):
        return True

    return (
        isinstance(exc, APIStatusError)
        and (exc.status_code == 429 or exc.status_code >= 500)
    )


async def call_llm(
    client: AsyncOpenAI,
    context: Context,
    *,
    model: str,
    system_prompt: str,
    tools: list[dict[str, Any]],
    max_tokens: int = 300,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> ChatCompletion:

    for attempt in range(max_attempts):
        try:
            return await client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *context.messages,
                ],
                tools=openai_tools(tools),
            )
        except (APIConnectionError, APIStatusError) as exc:
            is_last_attempt = attempt == max_attempts - 1
            if not is_retryable_llm_error(exc) or is_last_attempt:
                raise

            delay = base_delay * 2**attempt + random.uniform(0, 0.5)
            print(
                f"模型请求失败，{delay:.2f} 秒后重试 "
                f"({attempt + 2}/{max_attempts}): {type(exc).__name__}"
            )
            await asyncio.sleep(delay)

    raise RuntimeError("模型重试循环意外结束")


def assistant_message(message: ChatCompletionMessage) -> dict[str, Any]:
    """把 SDK assistant message 转成可回放的标准字典。"""
    result: dict[str, Any] = {
        "role": "assistant",
        "content": message.content,
    }
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]
    return result


async def execute_tools(
    message: ChatCompletionMessage,
    registry: Any,
    tracker: ToolCallTracker | None = None,
    tool_timeout: float = 300.0,
) -> list[dict[str, Any]]:
    """按顺序执行 function calls，并生成匹配的 tool messages。"""
    if tool_timeout <= 0:
        raise ValueError("tool_timeout 必须大于 0")

    tool_results: list[dict[str, Any]] = []
    for tool_call in message.tool_calls or []:
        name = tool_call.function.name
        try:
            input_data = json.loads(tool_call.function.arguments or "{}")
            if not isinstance(input_data, dict):
                raise TypeError("工具输入必须是 object")
        except (TypeError, json.JSONDecodeError) as exc:
            content = f"工具 {name} 参数 JSON 无效: {exc}"
            print(content)
            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": content,
                }
            )
            continue

        if tracker is not None and not tracker.allow(name, input_data):
            content = (
                "检测到相同工具调用已连续重复 "
                f"{tracker.max_consecutive} 次，请停止重复调用并采取下一步行动。"
            )
            print(f"拦截重复调用: {name} {input_data}")
        else:
            print(f"调用工具: {name} {input_data}")
            try:
                execution = await asyncio.wait_for(
                    registry.execute_with_status(name, input_data),
                    timeout=tool_timeout,
                )
                content = execution.content
            except TimeoutError:
                content = (
                    f"工具 {name} 执行超时（超过 {tool_timeout:g} 秒）"
                )
            print(f"工具结果: {content}")

        tool_results.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content,
            }
        )
    return tool_results
