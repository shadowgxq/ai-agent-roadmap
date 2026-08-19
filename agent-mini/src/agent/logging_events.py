"""Helpers for the structured logging channel, separate from UI events."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openai.types.chat import ChatCompletion

from .cost import CostBreakdown

if TYPE_CHECKING:
    from .loop import RunStats


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *message_args: Any,
    event: str,
    trace: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    console_message: str | None = None,
    **logging_kwargs: Any,
) -> None:
    """Emit one structured log record; this does not publish a UI event."""
    extra: dict[str, Any] = {
        "event": event,
        "trace": dict(trace) if trace is not None else None,
        "data": dict(data) if data is not None else {},
    }
    if console_message is not None:
        extra["console_message"] = console_message
    logger.log(
        level,
        message,
        *message_args,
        extra=extra,
        **logging_kwargs,
    )


def build_run_started_data(
    *,
    task: str,
    workdir: Path | str,
    model: str,
    main_model: str,
    small_model: str | None,
    router_model: str | None,
    router_enabled: bool,
    prompt_cache_enabled: bool,
    prompt_cache_key: str,
    prompt_cache_retention: str | None,
    max_turns: int,
    start_turn: int,
    additional: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared payload for ``run.started`` and ``run.resumed``."""
    data: dict[str, Any] = {
        "task": task,
        "workdir": str(workdir),
        "model": model,
        "main_model": main_model,
        "small_model": small_model,
        "router_model": router_model,
        "router_enabled": router_enabled,
        "prompt_cache_enabled": prompt_cache_enabled,
        "prompt_cache_key": prompt_cache_key,
        "prompt_cache_retention": prompt_cache_retention,
        "max_turns": max_turns,
        "start_turn": start_turn,
    }
    if additional:
        data.update(additional)
    return data


def build_run_usage_data(stats: RunStats) -> dict[str, Any]:
    """Build the main-agent, subagent, and aggregate usage payload."""
    total_stats = stats.aggregate()
    main_tokens = stats.total_tokens
    total_tokens = total_stats.total_tokens
    subagent_turns = total_stats.turns - stats.turns
    subagent_input_tokens = total_stats.input_tokens - stats.input_tokens
    subagent_cache_read_tokens = (
        total_stats.cache_read_input_tokens
        - stats.cache_read_input_tokens
    )
    subagent_cache_creation_tokens = (
        total_stats.cache_creation_input_tokens
        - stats.cache_creation_input_tokens
    )
    subagent_output_tokens = total_stats.output_tokens - stats.output_tokens
    subagent_compact_calls = total_stats.compact_calls - stats.compact_calls
    subagent_compact_tokens = (
        total_stats.compact_tokens - stats.compact_tokens
    )
    subagent_tokens = total_tokens - main_tokens

    return {
        "main": {
            "turns": stats.turns,
            "input_tokens": stats.input_tokens,
            "cache_read_input_tokens": stats.cache_read_input_tokens,
            "cache_creation_input_tokens": (
                stats.cache_creation_input_tokens
            ),
            "output_tokens": stats.output_tokens,
            "router_calls": stats.router_calls,
            "router_model": stats.router_model,
            "route": stats.route,
            "router_input_tokens": stats.router_input_tokens,
            "router_cache_read_input_tokens": (
                stats.router_cache_read_input_tokens
            ),
            "router_cache_creation_input_tokens": (
                stats.router_cache_creation_input_tokens
            ),
            "router_output_tokens": stats.router_output_tokens,
            "router_tokens": stats.router_tokens,
            "compact_calls": stats.compact_calls,
            "compact_input_tokens": stats.compact_input_tokens,
            "compact_cache_read_input_tokens": (
                stats.compact_cache_read_input_tokens
            ),
            "compact_cache_creation_input_tokens": (
                stats.compact_cache_creation_input_tokens
            ),
            "compact_output_tokens": stats.compact_output_tokens,
            "compact_tokens": stats.compact_tokens,
            "total_tokens": main_tokens,
        },
        "subagents": {
            "runs": len(stats.subagent_runs),
            "turns": subagent_turns,
            "input_tokens": subagent_input_tokens,
            "cache_read_input_tokens": subagent_cache_read_tokens,
            "cache_creation_input_tokens": subagent_cache_creation_tokens,
            "output_tokens": subagent_output_tokens,
            "compact_calls": subagent_compact_calls,
            "compact_tokens": subagent_compact_tokens,
            "total_tokens": subagent_tokens,
        },
        "total": {
            "turns": total_stats.turns,
            "input_tokens": total_stats.input_tokens,
            "cache_read_input_tokens": total_stats.cache_read_input_tokens,
            "cache_creation_input_tokens": (
                total_stats.cache_creation_input_tokens
            ),
            "output_tokens": total_stats.output_tokens,
            "router_calls": total_stats.router_calls,
            "router_model": total_stats.router_model,
            "route": total_stats.route,
            "router_input_tokens": total_stats.router_input_tokens,
            "router_cache_read_input_tokens": (
                total_stats.router_cache_read_input_tokens
            ),
            "router_cache_creation_input_tokens": (
                total_stats.router_cache_creation_input_tokens
            ),
            "router_output_tokens": total_stats.router_output_tokens,
            "router_tokens": total_stats.router_tokens,
            "compact_calls": total_stats.compact_calls,
            "compact_input_tokens": total_stats.compact_input_tokens,
            "compact_cache_read_input_tokens": (
                total_stats.compact_cache_read_input_tokens
            ),
            "compact_cache_creation_input_tokens": (
                total_stats.compact_cache_creation_input_tokens
            ),
            "compact_output_tokens": total_stats.compact_output_tokens,
            "compact_tokens": total_stats.compact_tokens,
            "total_tokens": total_tokens,
            "trajectory": total_stats.trajectory_metrics(),
        },
    }


def build_cost_data(
    cost: CostBreakdown,
    *,
    include_legacy: bool = False,
) -> dict[str, Any]:
    """Build canonical cost data and optionally expose legacy flat fields."""
    return cost.output_fields() if include_legacy else {"cost": cost.to_dict()}


def build_cost_event_data(cost: CostBreakdown) -> dict[str, Any]:
    """Build the CLI cost-event payload, including old consumer aliases."""
    return {
        "currency": cost.currency,
        "amount": cost.total_usd,
        **build_cost_data(cost, include_legacy=True),
    }


def build_run_completed_data(
    *,
    response: ChatCompletion,
    stats: RunStats,
    selected_model: str,
    router_enabled: bool,
    prompt_cache_enabled: bool,
    prompt_cache_key: str,
    prompt_cache_retention: str | None,
    cost: CostBreakdown,
    duration_s: float,
) -> dict[str, Any]:
    """Build the single canonical payload for ``run.completed``."""
    total_stats = stats.aggregate()
    return {
        "status": "completed",
        "finish_reason": response.choices[0].finish_reason,
        "trace_id": stats.trace_id,
        "trace_url": stats.trace_url,
        "router_enabled": router_enabled,
        "prompt_cache_enabled": prompt_cache_enabled,
        "prompt_cache_key": prompt_cache_key,
        "prompt_cache_retention": prompt_cache_retention,
        "route": stats.route,
        "router_model": stats.router_model,
        "selected_model": stats.selected_model or selected_model,
        "router_fallback": stats.router_fallback,
        "cache_read_input_tokens": total_stats.cache_read_input_tokens,
        "cache_creation_input_tokens": (
            total_stats.cache_creation_input_tokens
        ),
        **build_cost_data(cost, include_legacy=True),
        "duration_s": round(duration_s, 3),
    }
