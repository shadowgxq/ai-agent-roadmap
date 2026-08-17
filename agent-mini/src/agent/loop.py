"""连接模型、消息上下文和工具执行的 Agent 核心流程组件。"""

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from langfuse import Langfuse
from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage

from .cache import PromptCacheConfig
from .compact import compact, hard_truncate
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


def _is_verification_command(command: Any) -> bool:
    """判断 Shell 命令是否明显在执行测试或验证。"""
    if not isinstance(command, str):
        return False

    verification_patterns = (
        r"\bpytest\b",
        r"\bpython(?:3)?\s+-m\s+(?:pytest|unittest)\b",
        r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b",
        r"\b(?:go\s+test|cargo\s+test|make\s+test)\b",
    )
    for segment in re.split(r"&&|\|\||[;\n]", command.lower()):
        segment = segment.strip()
        if re.match(r"^(?:rg|grep|git\s+grep|find|sed|awk|cat)\b", segment):
            continue
        if any(re.search(pattern, segment) for pattern in verification_patterns):
            return True
    return False


@dataclass
class RunStats:
    """记录模型用量、递归 SubAgent 用量和执行轨迹指标。"""

    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    compact_calls: int = 0
    compact_input_tokens: int = 0
    compact_output_tokens: int = 0
    compact_cache_read_input_tokens: int = 0
    compact_cache_creation_input_tokens: int = 0
    tool_call_count: int = 0
    mcp_tool_call_count: int = 0
    subagent_tool_call_count: int = 0
    verification_command_count: int = 0
    tool_failure_count: int = 0
    recovered_after_tool_failure: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    subagent_runs: list["RunStats"] = field(default_factory=list)
    trace_id: str | None = None
    trace_url: str | None = None

    @property
    def model_tokens(self) -> int:
        """当前 Agent 决策模型调用的 token 总量。"""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )

    @property
    def compact_tokens(self) -> int:
        """当前 Agent 发起的 compact 模型调用 token 总量。"""
        return (
            self.compact_input_tokens
            + self.compact_output_tokens
            + self.compact_cache_read_input_tokens
            + self.compact_cache_creation_input_tokens
        )

    @property
    def total_tokens(self) -> int:
        """当前 Agent 的决策调用与 compact 调用 token 总量。"""
        return self.model_tokens + self.compact_tokens

    @property
    def subagent_used(self) -> bool:
        """本次运行是否实际调用过 SubAgent 工具。"""
        return self.subagent_tool_call_count > 0

    @property
    def mcp_used(self) -> bool:
        """本次运行是否实际调用过 MCP 工具。"""
        return self.mcp_tool_call_count > 0

    @property
    def verification_command_used(self) -> bool:
        """本次运行是否实际执行过测试或验证命令。"""
        return self.verification_command_count > 0

    def record_tool_call(
        self,
        name: str,
        input_data: dict[str, Any] | None = None,
        *,
        tool_call_id: str | None = None,
        turn: int | None = None,
    ) -> None:
        """记录一次模型发起的工具调用及其来源/用途。"""
        self.tool_call_count += 1
        if name == "spawn_subagent":
            self.subagent_tool_call_count += 1
        if "__" in name:
            self.mcp_tool_call_count += 1
        if name == "run_shell" and _is_verification_command(
            (input_data or {}).get("command")
        ):
            self.verification_command_count += 1
        self.tool_calls.append(
            {
                "id": tool_call_id,
                "name": name,
                "arguments": dict(input_data or {}),
                "turn": turn,
                "status": "pending",
            }
        )

    def record_tool_result(
        self,
        status: str,
        content: str = "",
        *,
        tool_call_id: str | None = None,
    ) -> None:
        """记录工具失败，并识别失败后的后续恢复。"""
        failed = status != "ok"
        if not failed and isinstance(content, str):
            match = re.match(r"\s*exit_code:\s*(-?\d+)", content)
            failed = match is not None and int(match.group(1)) != 0
        if failed:
            self.tool_failure_count += 1
        elif self.tool_failure_count > 0:
            self.recovered_after_tool_failure = True
        for record in reversed(self.tool_calls):
            if tool_call_id is not None and record.get("id") != tool_call_id:
                continue
            if record.get("status") == "pending":
                record["status"] = status
                break

    def trajectory_metrics(self) -> dict[str, Any]:
        """返回适合日志、报告和 Langfuse metadata 的轨迹指标。"""
        return {
            "subagent_used": self.subagent_used,
            "mcp_used": self.mcp_used,
            "verification_command_used": self.verification_command_used,
            "tool_call_count": self.tool_call_count,
            "tool_failure_count": self.tool_failure_count,
            "recovered_after_tool_failure": (
                self.recovered_after_tool_failure
            ),
        }

    def add_compact_usage(self, usage: "UsageTokens") -> None:
        """累计一次已返回响应的 compact 模型调用。"""
        self.compact_calls += 1
        self.compact_input_tokens += usage.input_tokens
        self.compact_output_tokens += usage.output_tokens
        self.compact_cache_read_input_tokens += usage.cache_read_input_tokens
        self.compact_cache_creation_input_tokens += (
            usage.cache_creation_input_tokens
        )

    def aggregate(self) -> "RunStats":
        """返回当前 Agent 及所有子 Agent 的汇总统计。"""
        total = RunStats(
            turns=self.turns,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            compact_calls=self.compact_calls,
            compact_input_tokens=self.compact_input_tokens,
            compact_output_tokens=self.compact_output_tokens,
            compact_cache_read_input_tokens=(
                self.compact_cache_read_input_tokens
            ),
            compact_cache_creation_input_tokens=(
                self.compact_cache_creation_input_tokens
            ),
            tool_call_count=self.tool_call_count,
            mcp_tool_call_count=self.mcp_tool_call_count,
            subagent_tool_call_count=self.subagent_tool_call_count,
            verification_command_count=self.verification_command_count,
            tool_failure_count=self.tool_failure_count,
            recovered_after_tool_failure=(
                self.recovered_after_tool_failure
            ),
            tool_calls=[dict(call) for call in self.tool_calls],
            trace_id=self.trace_id,
            trace_url=self.trace_url,
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
            total.compact_calls += child_total.compact_calls
            total.compact_input_tokens += child_total.compact_input_tokens
            total.compact_output_tokens += child_total.compact_output_tokens
            total.compact_cache_read_input_tokens += (
                child_total.compact_cache_read_input_tokens
            )
            total.compact_cache_creation_input_tokens += (
                child_total.compact_cache_creation_input_tokens
            )
            total.tool_call_count += child_total.tool_call_count
            total.mcp_tool_call_count += child_total.mcp_tool_call_count
            total.subagent_tool_call_count += (
                child_total.subagent_tool_call_count
            )
            total.verification_command_count += (
                child_total.verification_command_count
            )
            total.tool_failure_count += child_total.tool_failure_count
            total.recovered_after_tool_failure = (
                total.recovered_after_tool_failure
                or child_total.recovered_after_tool_failure
            )
            total.tool_calls.extend(
                dict(call) for call in child_total.tool_calls
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
    langfuse_client: Langfuse | None = None,
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

    def enforce_cost_limit() -> None:
        """在任意模型调用记账后检查本次运行预算。"""
        if max_cost_usd is None or cost_estimator is None:
            return
        current_cost = cost_estimator(stats)
        if current_cost is None:
            raise ValueError("缺少完整的模型价格配置，无法执行费用熔断")
        if current_cost > max_cost_usd:
            raise CostLimitExceeded(
                max_cost_usd=max_cost_usd,
                actual_cost_usd=current_cost,
                stats=stats,
            )

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
        compact_strategy: Literal["summary", "hard_truncate"] | None = None
        if (
            compact_enabled
            and last_context_tokens is not None
            and last_context_tokens
            >= compact_threshold * context_window_tokens
        ):
            compact_error: Exception | None = None
            compact_calls_before = stats.compact_calls

            def record_compact_usage(raw_usage: Any) -> dict[str, int]:
                usage = extract_usage_tokens(raw_usage)
                stats.add_compact_usage(usage)
                logger.info(
                    "compact 模型用量",
                    extra={
                        "event": "agent.context_compact_model_usage",
                        "trace": trace.event_context(turn),
                        "data": {
                            "model": compact_model or model,
                            "input_tokens": usage.input_tokens,
                            "cache_read_input_tokens": (
                                usage.cache_read_input_tokens
                            ),
                            "cache_creation_input_tokens": (
                                usage.cache_creation_input_tokens
                            ),
                            "output_tokens": usage.output_tokens,
                            "total_tokens": (
                                usage.input_tokens
                                + usage.cache_read_input_tokens
                                + usage.cache_creation_input_tokens
                                + usage.output_tokens
                            ),
                        },
                    },
                )
                return {
                    "input": usage.input_tokens,
                    "output": usage.output_tokens,
                    "cache_read_input_tokens": (
                        usage.cache_read_input_tokens
                    ),
                    "cache_creation_input_tokens": (
                        usage.cache_creation_input_tokens
                    ),
                }

            try:
                compacted_messages = await compact(
                    client,
                    context.messages,
                    model=compact_model or model,
                    keep_recent=compact_keep_recent,
                    max_tokens=compact_max_tokens,
                    usage_callback=record_compact_usage,
                    langfuse_client=langfuse_client,
                    turn=turn,
                    before_tokens=last_context_tokens,
                )
                validated_messages = Context(compacted_messages).messages
                compact_strategy = "summary"
            except Exception as exc:
                compact_error = exc
                logger.warning(
                    "上下文摘要最终失败，改用完整轮次硬裁剪: %s",
                    type(exc).__name__,
                    extra={
                        "event": "agent.context_compact_failed",
                        "trace": trace.event_context(turn),
                        "data": {
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    },
                )
                try:
                    truncated_messages = hard_truncate(
                        context.messages,
                        keep_recent=compact_keep_recent,
                    )
                    validated_messages = Context(truncated_messages).messages
                    compact_strategy = "hard_truncate"
                except Exception as fallback_exc:
                    validated_messages = context.messages
                    compact_strategy = None
                    logger.error(
                        "上下文硬裁剪失败，保留原上下文继续执行: %s",
                        type(fallback_exc).__name__,
                        extra={
                            "event": "agent.context_compact_fallback_failed",
                            "trace": trace.event_context(turn),
                            "data": {
                                "error_type": type(fallback_exc).__name__,
                                "error": str(fallback_exc),
                            },
                        },
                    )

            if stats.compact_calls > compact_calls_before:
                enforce_cost_limit()

            if validated_messages != context.messages:
                compact_before_tokens = last_context_tokens
                before_message_count = len(context.messages)
                context.messages = validated_messages
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
                            "strategy": compact_strategy,
                            "fallback_error": (
                                str(compact_error)
                                if compact_error is not None
                                else None
                            ),
                        },
                    },
                )

        llm_started_at = time.perf_counter()
        response = await call_llm(
            # 计时覆盖完整的请求和重试过程；token/cost 仍交给 Langfuse。
            client,
            context,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            max_tokens=max_tokens,
            prompt_cache=prompt_cache,
            trace=trace,
            turn=turn,
            langfuse_client=langfuse_client,
        )
        message = response.choices[0].message
        text = message_text(message)
        tool_call_names = [
            tool_call.function.name for tool_call in message.tool_calls or []
        ]
        llm_data = {
            "turn": turn,
            "duration_ms": round((time.perf_counter() - llm_started_at) * 1000),
            "text_preview": local_text_preview(text) if text else None,
            "tool_calls": tool_call_names,
            "finish_reason": response.choices[0].finish_reason,
        }
        if tool_call_names:
            text_prefix = f"{local_text_preview(text)} | " if text else ""
            console_message = (
                f"Turn {turn} → {text_prefix}tools: "
                f"{', '.join(tool_call_names)}"
            )
        else:
            console_message = f"Turn {turn} → final answer"
        logger.info(
            "LLM 完成: turn=%s tools=%s",
            turn,
            len(tool_call_names),
            extra={
                "event": "llm.completed",
                "trace": trace.event_context(turn),
                "console_message": console_message,
                "data": llm_data,
            },
        )
        if text:
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
                "strategy": compact_strategy,
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
                # f"上下文用量: turn={turn} context_tokens=unknown "
                f"window={context_window_tokens} usage=unknown%"
            )
        else:
            context_message = (
                # f"上下文用量: turn={turn} context_tokens={context_tokens} "
                f"window={context_window_tokens} "
                f"usage={context_usage_percent:.2f}%"
            )
        # logger.info(
        #     "上下文用量",
        #     extra={
        #         "event": "agent.context_usage",
        #         "trace": trace.event_context(turn),
        #         "console_message": context_message,
        #         "data": context_usage_data,
        #     },
        # )
        await emit_event(event_callback, "context_usage", context_usage_data)

        stats.turns += 1
        stats.input_tokens += token_usage.input_tokens
        stats.cache_read_input_tokens += token_usage.cache_read_input_tokens
        stats.cache_creation_input_tokens += (
            token_usage.cache_creation_input_tokens
        )
        stats.output_tokens += token_usage.output_tokens

        enforce_cost_limit()

        context.append_assistant(assistant_message(message))

        if not message.tool_calls:
            if checkpoint_callback is not None:
                checkpoint_callback(context, stats, turn, "completed")
            logger.info(
                "Agent 最终回答",
                extra={
                    "event": "agent.final_answer",
                    "trace": trace.event_context(turn),
                    "console_message": f"Final answer: {text}",
                    "data": {
                        "turn": turn,
                        "text": text,
                        "finish_reason": response.choices[0].finish_reason,
                    },
                },
            )
            logger.info(
                "Agent 完成: %s",
                trace.agent_id,
                extra={
                    "event": "agent.completed",
                    "trace": trace.event_context(turn),
                    "console_message": f"Agent completed: {stats.turns} turns",
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
            stats=stats,
            trace=trace,
            turn=turn,
            langfuse_client=langfuse_client,
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
    langfuse_client: Langfuse | None = None,
) -> ChatCompletion:

    for attempt in range(max_attempts):
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                *context.messages,
            ]
            observation_context = (
                langfuse_client.start_as_current_observation(
                    as_type="generation",
                    name="agent.llm",
                    model=model,
                    input=messages,
                    metadata={
                        "turn": turn,
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "max_tokens": max_tokens,
                    },
                )
                if langfuse_client is not None
                else nullcontext()
            )
            request_error: APIConnectionError | APIStatusError | None = None
            response: ChatCompletion | None = None
            with observation_context as generation:
                try:
                    response = await client.chat.completions.create(
                        model=model,
                        max_tokens=max_tokens,
                        messages=messages,
                        tools=openai_tools(tools),
                        **(
                            prompt_cache.request_kwargs()
                            if prompt_cache is not None
                            else {}
                        ),
                    )
                except (APIConnectionError, APIStatusError) as exc:
                    request_error = exc
                    if generation is not None:
                        generation.update(
                            level="ERROR",
                            status_message=type(exc).__name__,
                            metadata={
                                "turn": turn,
                                "attempt": attempt + 1,
                                "max_attempts": max_attempts,
                                "max_tokens": max_tokens,
                                "error_type": type(exc).__name__,
                                "status_code": getattr(
                                    exc, "status_code", None
                                ),
                            },
                        )
                if generation is not None and response is not None:
                    usage = extract_usage_tokens(response.usage)
                    generation.update(
                        output=assistant_message(
                            response.choices[0].message
                        ),
                        usage_details={
                            "input": usage.input_tokens,
                            "output": usage.output_tokens,
                            "cache_read_input_tokens": (
                                usage.cache_read_input_tokens
                            ),
                            "cache_creation_input_tokens": (
                                usage.cache_creation_input_tokens
                            ),
                        },
                        metadata={
                            "turn": turn,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "max_tokens": max_tokens,
                            "finish_reason": (
                                response.choices[0].finish_reason
                            ),
                        },
                    )
            if request_error is not None:
                raise request_error
            if response is None:
                raise RuntimeError("模型调用没有返回响应")
            return response
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


def local_text_preview(text: str, limit: int = 200) -> str:
    """生成不会撑爆终端的单行文本预览。"""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + f"...[truncated, total={len(normalized)} chars]"


async def execute_tools(
    message: ChatCompletionMessage,
    registry: Any,
    tracker: ToolCallTracker | None = None,
    tool_timeout: float = 300.0,
    *,
    stats: RunStats | None = None,
    trace: AgentTrace | None = None,
    turn: int | None = None,
    langfuse_client: Langfuse | None = None,
) -> list[dict[str, Any]]:
    """按顺序执行 function calls，并生成匹配的 tool messages。"""
    if tool_timeout <= 0:
        raise ValueError("tool_timeout 必须大于 0")

    tool_results: list[dict[str, Any]] = []
    tool_calls = message.tool_calls or []
    for tool_call in tool_calls:
        name = tool_call.function.name
        tool_started_at = time.perf_counter()
        trace_context = (
            trace.event_context(turn) if trace is not None else None
        )
        try:
            input_data = json.loads(tool_call.function.arguments or "{}")
            if not isinstance(input_data, dict):
                raise TypeError("工具输入必须是 object")
        except (TypeError, json.JSONDecodeError) as exc:
            content = f"工具 {name} 参数 JSON 无效: {exc}"
            if stats is not None:
                stats.record_tool_call(
                    name,
                    {},
                    tool_call_id=tool_call.id,
                    turn=turn,
                )
                stats.record_tool_result(
                    "invalid_arguments",
                    content,
                    tool_call_id=tool_call.id,
                )
            logger.error(
                content,
                extra={
                    "event": "tool.completed",
                    "trace": trace_context,
                    "console_message": f"→ {name} ✗ invalid arguments",
                    "data": {
                        "tool": name,
                        "status": "invalid_arguments",
                        "duration_ms": round(
                            (time.perf_counter() - tool_started_at) * 1000
                        ),
                        "result_size": len(content),
                        "error": local_text_preview(content),
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

        observation_context = (
            langfuse_client.start_as_current_observation(
                as_type="tool",
                name=name,
                input=input_data,
                metadata={
                    "turn": turn,
                    "tool_call_id": tool_call.id,
                },
            )
            if langfuse_client is not None
            else nullcontext()
        )
        with observation_context as tool_observation:
            if stats is not None:
                stats.record_tool_call(
                    name,
                    input_data,
                    tool_call_id=tool_call.id,
                    turn=turn,
                )
            if tracker is not None and not tracker.allow(name, input_data):
                content = (
                    "检测到相同工具调用已连续重复 "
                    f"{tracker.max_consecutive} 次，请停止重复调用并采取下一步行动。"
                )
                status = "blocked"
            else:
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

            duration_ms = round(
                (time.perf_counter() - tool_started_at) * 1000
            )
            preview = local_text_preview(content)
            console_status = "✓" if status == "ok" else "✗"
            log_method = logger.info if status == "ok" else logger.warning
            log_method(
                "工具完成: %s (%s)",
                name,
                status,
                extra={
                    "event": "tool.completed",
                    "trace": trace_context,
                    "console_message": (
                        f"→ {name} {console_status} ({duration_ms}ms)"
                    ),
                    "data": {
                        "tool": name,
                        "status": status,
                        "duration_ms": duration_ms,
                        "result_size": len(content),
                        "preview": preview,
                        **(
                            {"error": preview}
                            if status != "ok"
                            else {}
                        ),
                    },
                },
            )

            if stats is not None:
                stats.record_tool_result(
                    status,
                    content,
                    tool_call_id=tool_call.id,
                )
            if tool_observation is not None:
                tool_observation.update(
                    output=content,
                    metadata={
                        "turn": turn,
                        "tool_call_id": tool_call.id,
                        "status": status,
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
