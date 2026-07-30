"""agent-mini 的命令行入口。"""

import argparse
import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import APIError


if __package__:
    from .agent.config import AgentSettings
    from .agent.cost import estimate_cost
    from .agent.loop import MaxTurnsExceeded, RunStats
    from .agent.runtime import run_coding_agent
    from .agent.logging_config import configure_logging, get_logger
else:
    from agent.config import AgentSettings
    from agent.cost import estimate_cost
    from agent.loop import MaxTurnsExceeded, RunStats
    from agent.runtime import run_coding_agent
    from agent.logging_config import configure_logging, get_logger


logger = get_logger("cli")


def parse_args() -> argparse.Namespace:
    """解析 Coding Agent 的命令行参数。"""
    parser = argparse.ArgumentParser(
        description="在指定项目中运行 Coding Agent。",
    )

    parser.add_argument(
        "task",
        help="交给 Agent 完成的任务。",
    )
    parser.add_argument(
        "--dir",
        dest="workdir",
        type=Path,
        default=Path.cwd(),
        help="Agent 操作的项目目录，默认为当前目录。",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="覆盖环境配置中的模型名称。",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="覆盖 Agent 最大循环轮数。",
    )
    parser.add_argument(
        "--no-subagent",
        action="store_false",
        dest="enable_subagent",
        help="禁用探索型 SubAgent，用于对比实验。",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="JSON 运行日志；默认 logs/agent.json，每次运行覆盖写入。",
    )

    args = parser.parse_args()
    if args.max_turns is not None and args.max_turns < 1:
        parser.error("--max-turns 必须大于 0")
    return args


def extract_text(message: Any) -> str:
    """提取 Chat Completions 响应中的 assistant 文本。"""
    return message.choices[0].message.content or "(模型未返回文本)"


def log_stats(
    stats: RunStats,
    *,
    trace: dict[str, str] | None = None,
) -> None:
    """记录一次 Agent 运行累计的模型用量。"""
    total_stats = stats.aggregate()
    main_tokens = (
        stats.input_tokens
        + stats.cache_read_input_tokens
        + stats.cache_creation_input_tokens
        + stats.output_tokens
    )
    total_tokens = (
        total_stats.input_tokens
        + total_stats.cache_read_input_tokens
        + total_stats.cache_creation_input_tokens
        + total_stats.output_tokens
    )
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
    subagent_tokens = total_tokens - main_tokens
    logger.info(
        (
            "运行统计: main_turns=%s, subagent_runs=%s, "
            "subagent_turns=%s, main_tokens=%s, "
            "subagent_tokens=%s, total_tokens=%s"
        ),
        stats.turns,
        len(stats.subagent_runs),
        subagent_turns,
        main_tokens,
        subagent_tokens,
        total_tokens,
        extra={
            "event": "run.usage",
            "trace": trace,
            "data": {
                "main": {
                    "turns": stats.turns,
                    "input_tokens": stats.input_tokens,
                    "cache_read_input_tokens": (
                        stats.cache_read_input_tokens
                    ),
                    "cache_creation_input_tokens": (
                        stats.cache_creation_input_tokens
                    ),
                    "output_tokens": stats.output_tokens,
                    "total_tokens": main_tokens,
                },
                "subagents": {
                    "runs": len(stats.subagent_runs),
                    "turns": subagent_turns,
                    "input_tokens": subagent_input_tokens,
                    "cache_read_input_tokens": subagent_cache_read_tokens,
                    "cache_creation_input_tokens": (
                        subagent_cache_creation_tokens
                    ),
                    "output_tokens": subagent_output_tokens,
                    "total_tokens": subagent_tokens,
                },
                "total": {
                    "turns": total_stats.turns,
                    "input_tokens": total_stats.input_tokens,
                    "cache_read_input_tokens": (
                        total_stats.cache_read_input_tokens
                    ),
                    "cache_creation_input_tokens": (
                        total_stats.cache_creation_input_tokens
                    ),
                    "output_tokens": total_stats.output_tokens,
                    "total_tokens": total_tokens,
                },
            },
        },
    )


def log_cost(
    stats: RunStats,
    settings: AgentSettings,
    *,
    trace: dict[str, str] | None = None,
) -> None:
    """价格配置完整时打印预估费用。"""
    cost = estimate_cost(stats, settings)
    if cost is None:
        logger.info(
            "预估费用: 未配置完整的模型单价",
            extra={"event": "run.cost_unavailable", "trace": trace},
        )
        return

    logger.info(
        "预估费用: %s %.6f",
        settings.price_currency,
        cost,
        extra={
            "event": "run.cost",
            "trace": trace,
            "data": {"currency": settings.price_currency, "amount": cost},
        },
    )


async def main() -> None:
    """解析命令行参数，运行 Agent 并展示结果。"""
    args = parse_args()
    workdir = args.workdir.resolve()
    settings = AgentSettings()
    run_id = uuid4().hex
    trace = {"run_id": run_id, "agent_id": "main", "role": "main"}
    log_file = configure_logging(args.log_file or settings.log_file)
    logger.info(
        "详细日志: %s",
        log_file,
        extra={
            "event": "run.started",
            "trace": trace,
            "data": {
                "task": args.task,
                "workdir": str(workdir),
                "log_file": str(log_file),
                "model": args.model or settings.model,
                "max_turns": args.max_turns or settings.max_turns,
                "enable_subagent": args.enable_subagent,
            },
        },
    )

    try:
        final_response, stats = await run_coding_agent(
            task=args.task,
            workdir=workdir,
            settings=settings,
            model=args.model,
            max_turns=args.max_turns,
            run_id=run_id,
            enable_subagent=args.enable_subagent,
        )
    except MaxTurnsExceeded as exc:
        logger.error(
            "运行失败: %s",
            exc,
            extra={"event": "run.max_turns_exceeded", "trace": trace},
        )
        log_stats(exc.stats, trace=trace)
        log_cost(exc.stats, settings, trace=trace)
        return
    except APIError as exc:
        logger.error(
            "模型请求失败: %s",
            exc,
            extra={"event": "run.api_error", "trace": trace},
        )
        return

    log_stats(stats, trace=trace)
    log_cost(stats, settings, trace=trace)
    finish_reason = final_response.choices[0].finish_reason
    answer = extract_text(final_response)
    logger.info(
        "运行完成",
        extra={
            "event": "run.completed",
            "trace": trace,
            "console_message": f"最终回答: {answer}",
            "data": {"finish_reason": finish_reason, "answer": answer},
        },
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning(
            "运行已由用户中断。",
            extra={"event": "run.interrupted"},
        )
