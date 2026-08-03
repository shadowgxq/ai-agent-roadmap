"""连接模型、消息上下文和工具执行的 Agent 核心流程组件。"""

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage

from .cache import PromptCacheConfig
from .compact import compact
from .context import Context
from .logging_config import get_logger

logger = get_logger("agent.loop")

DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000

EventCallback = Callable[
    [str, dict[str, Any]],
    Awaitable[None] | None,
]


async def emit_event(
    callback: EventCallback | None,
    event: str,
    data: dict[str, Any],
) -> None:
    """通知可选观察者；观察者异常不应中断 Agent 主循环。"""
    if callback is None:
        return
    try:
        result = callback(event, data)
        if result is not None:
            await result
    except Exception:
        logger.exception("Agent 事件观察者执行失败: %s", event)


@dataclass(frozen=True)
class AgentTrace:
    """标识一次运行中的主 Agent 或 SubAgent。"""

    run_id: str
    agent_id: str
    role: str
    parent_agent_id: str | None = None

    def event_context(self, turn: int | None = None) -> dict[str, Any]:
        """生成附加到结构化日志事件的关联字段。"""
        context: dict[str, Any] = {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "role": self.role,
        }
        if self.parent_agent_id is not None:
            context["parent_agent_id"] = self.parent_agent_id
        if turn is not None:
            context["turn"] = turn
        return context


@dataclass
class RunStats:
    """记录模型调用统计，input_tokens 不包含缓存读写的输入。"""

    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    subagent_runs: list["RunStats"] = field(default_factory=list)

    def aggregate(self) -> "RunStats":
        """返回当前 Agent 及所有子 Agent 的汇总统计。"""
        total = RunStats(
            turns=self.turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
        )
        for child in self.subagent_runs:
            child_total = child.aggregate()
            total.turns += child_total.turns
            total.input_tokens += child_total.input_tokens
            total.output_tokens += child_total.output_tokens
            total.cache_read_input_tokens += (
                child_total.cache_read_input_tokens
            )
            total.cache_creation_input_tokens += (
                child_total.cache_creation_input_tokens
            )
        return total


@dataclass(frozen=True)
class UsageTokens:
    """Normalized token usage shared by supported provider formats."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    # Request context size, including cached input when reported separately.
    context_tokens: int | None = None


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
    details = next(
        (
            _usage_value(usage, field_name)
            for field_name in (
                "prompt_tokens_details",
                "input_tokens_details",
                "cache_details",
            )
            if _usage_value(usage, field_name) is not None
        ),
        None,
    )

    cache_read = _token_count(
        _usage_value(
            usage,
            "cache_read_input_tokens",
            "cache_read_tokens",
            "cached_tokens",
            "prompt_cache_hit_tokens",
            "cache_hit_tokens",
        )
    )
    if cache_read == 0:
        cache_read = _token_count(
            _usage_value(
                details,
                "cache_read_input_tokens",
                "cache_read_tokens",
                "cached_tokens",
                "prompt_cache_hit_tokens",
                "cache_hit_tokens",
            )
        )

    cache_creation = _token_count(
        _usage_value(
            usage,
            "cache_creation_input_tokens",
            "cache_creation_tokens",
            "cache_write_input_tokens",
            "cache_write_tokens",
            "prompt_cache_creation_tokens",
        )
    )
    if cache_creation == 0:
        cache_creation = _token_count(
            _usage_value(
                details,
                "cache_creation_input_tokens",
                "cache_creation_tokens",
                "cache_write_input_tokens",
                "cache_write_tokens",
                "prompt_cache_creation_tokens",
            )
        )

    explicit_input = _usage_value(usage, "input_tokens")
    raw_prompt_tokens = _usage_value(usage, "prompt_tokens")
    prompt_tokens = _token_count(raw_prompt_tokens)
    if explicit_input is not None:
        input_tokens = _token_count(explicit_input)
        context_tokens = input_tokens + cache_read + cache_creation
    else:
        # OpenAI-style prompt_tokens commonly includes cached input.
        input_tokens = max(prompt_tokens - cache_read - cache_creation, 0)
        context_tokens = prompt_tokens if raw_prompt_tokens is not None else None

    output_tokens = _token_count(
        _usage_value(usage, "output_tokens", "completion_tokens")
    )
    return UsageTokens(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
        context_tokens=context_tokens,
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
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS,
    cost_estimator: Callable[[RunStats], float | None] | None = None,
    max_cost_usd: float | None = None,
    prompt_cache: PromptCacheConfig | None = None,
    stats: RunStats | None = None,
    trace: AgentTrace | None = None,
    start_turn: int = 0,
    checkpoint_callback: Callable[
        [Context, RunStats, int, Literal["running", "completed"]], None
    ] | None = None,
    event_callback: EventCallback | None = None,
    compact_enabled: bool = False,
    compact_threshold: float = 0.7,
    compact_keep_recent: int = 4,
    compact_model: str | None = None,
    compact_max_tokens: int = 1000,
) -> tuple[ChatCompletion, RunStats]:
    """运行 Agent，直到模型结束或达到最大轮数。"""
    if start_turn < 0 or start_turn > max_turns:
        raise ValueError("start_turn 必须在 0 和 max_turns 之间")
    if context_window_tokens <= 0:
        raise ValueError("context_window_tokens 必须大于 0")
    if not 0 < compact_threshold < 1:
        raise ValueError("compact_threshold 必须在 0 和 1 之间")
    if compact_keep_recent < 1:
        raise ValueError("compact_keep_recent 必须大于 0")
    if compact_max_tokens < 1:
        raise ValueError("compact_max_tokens 必须大于 0")

    if max_cost_usd is not None:
        if max_cost_usd <= 0:
            raise ValueError("max_cost_usd 必须大于 0")
        if cost_estimator is None:
            raise ValueError("设置 max_cost_usd 时必须提供 cost_estimator")

    if trace is None:
        trace = AgentTrace(
            run_id=uuid4().hex,
            agent_id="main",
            role="main",
        )

    tools = registry.schemas()
    if stats is None:
        stats = RunStats()
    tracker = ToolCallTracker()
    logger.info(
        "Agent 开始: %s",
        trace.agent_id,
        extra={
            "event": "agent.started",
            "trace": trace.event_context(),
            "data": {
                "model": model,
                "max_turns": max_turns,
                "max_tokens": max_tokens,
                "message_count": len(context.messages),
                "tools": [tool["name"] for tool in tools],
            },
        },
    )
    last_context_tokens: int | None = None

    for turn in range(start_turn + 1, max_turns + 1):
        logger.info(
            "===== 第 %s/%s 轮 =====",
            turn,
            max_turns,
            extra={
                "event": "agent.turn_started",
                "trace": trace.event_context(turn),
                "data": {"max_turns": max_turns},
            },
        )
        compact_before_tokens: int | None = None
        if (
            compact_enabled
            and last_context_tokens is not None
            and last_context_tokens
            >= compact_threshold * context_window_tokens
        ):
            compacted_messages = await compact(
                client,
                context.messages,
                model=compact_model or model,
                keep_recent=compact_keep_recent,
                max_tokens=compact_max_tokens,
            )
            if compacted_messages != context.messages:
                compact_before_tokens = last_context_tokens
                before_message_count = len(context.messages)
                context.messages = compacted_messages
                context.assert_paired()
                logger.info(
                    "上下文压缩完成，等待下一次请求确认 token 用量",
                    extra={
                        "event": "agent.context_compacted",
                        "trace": trace.event_context(turn),
                        "console_message": (
                            f"[compact] before={compact_before_tokens} tokens, "
                            "after=pending"
                        ),
                        "data": {
                            "before_tokens": compact_before_tokens,
                            "before_message_count": before_message_count,
                            "after_message_count": len(context.messages),
                        },
                    },
                )

        response = await call_llm(
            client,
            context,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            max_tokens=max_tokens,
            prompt_cache=prompt_cache,
            trace=trace,
            turn=turn,
        )
        message = response.choices[0].message
        text = message_text(message)
        if text:
            logger.info(
                "模型返回文本",
                extra={
                    "event": "agent.model_text",
                    "trace": trace.event_context(turn),
                    "console_message": f"模型文本: {text}",
                    "data": {"text": text},
                },
            )
            await emit_event(
                event_callback,
                "text",
                {"turn": turn, "text": text},
            )

        token_usage = extract_usage_tokens(response.usage)
        if compact_before_tokens is not None:
            after_tokens = token_usage.context_tokens
            compact_data = {
                "turn": turn,
                "before_tokens": compact_before_tokens,
                "after_tokens": after_tokens,
            }
            logger.info(
                "上下文压缩用量",
                extra={
                    "event": "agent.compact_usage",
                    "trace": trace.event_context(turn),
                    "console_message": (
                        f"[compact] before={compact_before_tokens} tokens, "
                        f"after={after_tokens if after_tokens is not None else 'unknown'} "
                        "tokens"
                    ),
                    "data": compact_data,
                },
            )
            await emit_event(event_callback, "compact_usage", compact_data)

        last_context_tokens = token_usage.context_tokens

        context_tokens = token_usage.context_tokens
        context_usage_percent = (
            round(context_tokens / context_window_tokens * 100, 2)
            if context_tokens is not None
            else None
        )
        context_usage_data = {
            "turn": turn,
            "context_tokens": context_tokens,
            "context_window_tokens": context_window_tokens,
            "context_usage_percent": context_usage_percent,
            "available": context_tokens is not None,
        }
        if context_tokens is None:
            context_message = (
                f"上下文用量: turn={turn} context_tokens=unknown "
                f"window={context_window_tokens} usage=unknown%"
            )
        else:
            context_message = (
                f"上下文用量: turn={turn} context_tokens={context_tokens} "
                f"window={context_window_tokens} "
                f"usage={context_usage_percent:.2f}%"
            )
        logger.info(
            "上下文用量",
            extra={
                "event": "agent.context_usage",
                "trace": trace.event_context(turn),
                "console_message": context_message,
                "data": context_usage_data,
            },
        )
        await emit_event(event_callback, "context_usage", context_usage_data)

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
            if checkpoint_callback is not None:
                checkpoint_callback(context, stats, turn, "completed")
            logger.info(
                "Agent 完成: %s",
                trace.agent_id,
                extra={
                    "event": "agent.completed",
                    "trace": trace.event_context(turn),
                    "data": {
                        "turns": stats.turns,
                        "finish_reason": response.choices[0].finish_reason,
                    },
                },
            )
            await emit_event(
                event_callback,
                "done",
                {
                    "status": "completed",
                    "turn": turn,
                    "finish_reason": response.choices[0].finish_reason,
                },
            )
            return response, stats

        await emit_event(
            event_callback,
            "tool_call",
            {
                "turn": turn,
                "calls": [
                    {
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    }
                    for tool_call in message.tool_calls
                ],
            },
        )
        tool_results = await execute_tools(
            message,
            registry,
            tracker,
            trace=trace,
            turn=turn,
        )
        context.append_tool_results(tool_results)
        context.assert_paired()
        await emit_event(
            event_callback,
            "tool_result",
            {
                "turn": turn,
                "results": [
                    {
                        "tool_call_id": result["tool_call_id"],
                        "content": result["content"],
                    }
                    for result in tool_results
                ],
            },
        )
        if checkpoint_callback is not None:
            checkpoint_callback(context, stats, turn, "running")

    logger.error(
        "Agent 达到最大轮数: %s",
        max_turns,
        extra={
            "event": "agent.max_turns_exceeded",
            "trace": trace.event_context(max_turns),
            "data": {"max_turns": max_turns},
        },
    )
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
    prompt_cache: PromptCacheConfig | None = None,
    trace: AgentTrace | None = None,
    turn: int | None = None,
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
                **(
                    prompt_cache.request_kwargs()
                    if prompt_cache is not None
                    else {}
                ),
            )
        except (APIConnectionError, APIStatusError) as exc:
            is_last_attempt = attempt == max_attempts - 1
            if not is_retryable_llm_error(exc) or is_last_attempt:
                raise

            delay = base_delay * 2**attempt + random.uniform(0, 0.5)
            logger.warning(
                "模型请求失败，%.2f 秒后重试 (%s/%s): %s",
                delay,
                attempt + 2,
                max_attempts,
                type(exc).__name__,
                extra={
                    "event": "agent.model_retry",
                    "trace": (
                        trace.event_context(
                            turn) if trace is not None else None
                    ),
                    "data": {
                        "delay_s": delay,
                        "attempt": attempt + 2,
                        "max_attempts": max_attempts,
                        "error_type": type(exc).__name__,
                    },
                },
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
    *,
    trace: AgentTrace | None = None,
    turn: int | None = None,
) -> list[dict[str, Any]]:
    """按顺序执行 function calls，并生成匹配的 tool messages。"""
    if tool_timeout <= 0:
        raise ValueError("tool_timeout 必须大于 0")

    tool_results: list[dict[str, Any]] = []
    tool_calls = message.tool_calls or []
    for tool_call in tool_calls:
        name = tool_call.function.name
        trace_context = (
            trace.event_context(turn) if trace is not None else None
        )
        try:
            input_data = json.loads(tool_call.function.arguments or "{}")
            if not isinstance(input_data, dict):
                raise TypeError("工具输入必须是 object")
        except (TypeError, json.JSONDecodeError) as exc:
            content = f"工具 {name} 参数 JSON 无效: {exc}"
            logger.error(
                content,
                extra={
                    "event": "agent.tool_invalid_arguments",
                    "trace": trace_context,
                    "data": {
                        "tool": name,
                        "status": "invalid_arguments",
                        "error": str(exc),
                    },
                },
            )
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
            logger.warning(
                "拦截重复调用: %s %s",
                name,
                input_data,
                extra={
                    "event": "agent.tool_blocked",
                    "trace": trace_context,
                    "data": {
                        "tool": name,
                        "status": "blocked",
                        "arguments": input_data,
                    },
                },
            )
        else:
            logger.info(
                "工具开始: %s",
                name,
                extra={
                    "event": "agent.tool_started",
                    "trace": trace_context,
                    "console_message": f"调用工具: {name} {input_data}",
                    "data": {
                        "tool": name,
                        "arguments": input_data,
                    },
                },
            )
            try:
                execution = await asyncio.wait_for(
                    registry.execute_with_status(name, input_data),
                    timeout=tool_timeout,
                )
                content = execution.content
                status = "error" if execution.is_error else "ok"
            except TimeoutError:
                content = (
                    f"工具 {name} 执行超时（超过 {tool_timeout:g} 秒）"
                )
                status = "timeout"
            logger.info(
                "工具完成: %s (%s)",
                name,
                status,
                extra={
                    "event": "agent.tool_completed",
                    "trace": trace_context,
                    "console_message": f"工具结果: {content}",
                    "data": {
                        "tool": name,
                        "status": status,
                        "content": content,
                    },
                },
            )

        tool_results.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": content,
            }
        )
    return tool_results
