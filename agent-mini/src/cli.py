"""agent-mini 的命令行入口。"""

import argparse
import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import APIError


from .agent.checkpoint import load_checkpoint
from .agent.config import AgentSettings
from .agent.context import Context
from .agent.cost import estimate_cost
from .agent.git_snapshot import GitSnapshotError, rollback_to_sha
from .agent.loop import CostLimitExceeded, MaxTurnsExceeded, RunStats
from .agent.runtime import run_coding_agent
from .agent.logging_config import configure_logging, get_logger


logger = get_logger("cli")


def parse_args() -> argparse.Namespace:
    """解析 Coding Agent 的命令行参数。"""
    parser = argparse.ArgumentParser(
        description="在指定项目中运行 Coding Agent。",
    )

    parser.add_argument(
        "task",
        nargs="?",
        help="交给 Agent 完成的任务；使用 --resume 时省略。",
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
        "--checkpoint",
        "--enable-checkpoint",
        action="store_true",
        dest="checkpoint_enabled",
        help="启用 checkpoint，并在任务开始前创建 Git 起点快照；默认关闭。",
    )
    parser.add_argument(
        "--no-subagent",
        action="store_false",
        dest="enable_subagent",
        help="禁用探索型 SubAgent，用于对比实验。",
    )
    parser.add_argument(
        "--case-id",
        default=None,
        help="可选的 Eval case 标识，写入 Langfuse trace metadata。",
    )
    parser.add_argument(
        "--experiment",
        default=None,
        help="可选的实验名称，写入 Langfuse trace metadata。",
    )
    parser.add_argument(
        "--trace-tag",
        action="append",
        default=[],
        help="Langfuse trace 标签；可重复传入多个。",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="从指定 run_id 的 checkpoint 恢复任务。",
    )
    parser.add_argument(
        "--rollback",
        metavar="RUN_ID",
        help="将指定运行的工作目录回滚到任务开始前的 Git 快照。",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="JSON 运行日志；默认 logs/agent.json，每次运行覆盖写入。",
    )

    args = parser.parse_args()
    if args.resume and args.rollback:
        parser.error("--resume 和 --rollback 不能同时使用")
    if args.rollback and args.task:
        parser.error("--rollback 不能与新的 task 同时使用")
    if not args.resume and not args.rollback and not args.task:
        parser.error("必须提供 task，或使用 --resume RUN_ID")
    if args.resume and (
        args.model is not None
        or args.max_turns is not None
        or args.workdir != Path.cwd()
        or not args.enable_subagent
        or args.checkpoint_enabled
        or args.case_id is not None
        or args.experiment is not None
        or args.trace_tag
    ):
        parser.error(
            "--resume 会恢复原始模型、目录、轮数和 SubAgent 配置，"
            "并自动启用 checkpoint，不能同时覆盖这些参数"
        )
    if args.rollback and (
        args.model is not None
        or args.max_turns is not None
        or args.workdir != Path.cwd()
        or not args.enable_subagent
        or args.checkpoint_enabled
        or args.case_id is not None
        or args.experiment is not None
        or args.trace_tag
    ):
        parser.error("--rollback 只需要 RUN_ID，不能覆盖运行参数")
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
    logger.info(
        (
            "运行统计: main_turns=%s, subagent_runs=%s, "
            "subagent_turns=%s, compact_calls=%s, compact_tokens=%s, "
            "main_tokens=%s, "
            "subagent_tokens=%s, total_tokens=%s"
        ),
        stats.turns,
        len(stats.subagent_runs),
        subagent_turns,
        stats.compact_calls,
        stats.compact_tokens,
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
                    "cache_creation_input_tokens": (
                        subagent_cache_creation_tokens
                    ),
                    "output_tokens": subagent_output_tokens,
                    "compact_calls": subagent_compact_calls,
                    "compact_tokens": subagent_compact_tokens,
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
                    "compact_calls": total_stats.compact_calls,
                    "compact_input_tokens": (
                        total_stats.compact_input_tokens
                    ),
                    "compact_cache_read_input_tokens": (
                        total_stats.compact_cache_read_input_tokens
                    ),
                    "compact_cache_creation_input_tokens": (
                        total_stats.compact_cache_creation_input_tokens
                    ),
                    "compact_output_tokens": (
                        total_stats.compact_output_tokens
                    ),
                    "compact_tokens": total_stats.compact_tokens,
                    "total_tokens": total_tokens,
                    "trajectory": total_stats.trajectory_metrics(),
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

    if args.rollback:
        checkpoint = load_checkpoint(args.rollback)
        if checkpoint.start_sha is None:
            raise GitSnapshotError(
                f"运行 {checkpoint.run_id} 没有 Git 起点，无法回滚"
            )
        rollback_to_sha(Path(checkpoint.workdir), checkpoint.start_sha)
        print(
            f"已回滚运行 {checkpoint.run_id} 的工作目录到 "
            f"{checkpoint.start_sha}"
        )
        return

    settings = AgentSettings()

    if args.resume:
        checkpoint = load_checkpoint(args.resume)
        if checkpoint.status == "completed":
            raise ValueError(f"运行 {checkpoint.run_id} 已经完成，不能继续恢复")
        task = checkpoint.task
        workdir = Path(checkpoint.workdir).resolve()
        run_id = checkpoint.run_id
        model = checkpoint.model
        max_turns = checkpoint.max_turns
        max_tokens = checkpoint.max_tokens
        context_window_tokens = checkpoint.context_window_tokens
        max_cost_usd = checkpoint.max_cost_usd
        enable_subagent = checkpoint.enable_subagent
        trace_metadata = None
        trace_tags = None
        context = Context(checkpoint.messages)
        stats = checkpoint.stats.to_stats()
        start_turn = checkpoint.turn
        start_sha = checkpoint.start_sha
    else:
        task = args.task
        if task is None:
            raise RuntimeError("CLI 参数校验未提供 task")
        workdir = args.workdir.resolve()
        run_id = uuid4().hex
        model = args.model or settings.model
        max_turns = args.max_turns or settings.max_turns
        max_tokens = 3000
        context_window_tokens = settings.context_window_tokens
        max_cost_usd = None
        enable_subagent = args.enable_subagent
        trace_metadata = {
            key: value
            for key, value in {
                "case_id": args.case_id,
                "experiment": args.experiment,
            }.items()
            if value is not None
        }
        trace_tags = list(args.trace_tag)
        context = None
        stats = None
        start_turn = 0
        start_sha = None

    checkpoint_enabled = args.checkpoint_enabled or bool(args.resume)
    trace = {"run_id": run_id, "agent_id": "main", "role": "main"}
    log_file = configure_logging(args.log_file or settings.log_file)
    logger.info(
        "详细日志: %s",
        log_file,
        extra={
            "event": "run.resumed" if args.resume else "run.started",
            "trace": trace,
            "data": {
                "task": task,
                "workdir": str(workdir),
                "log_file": str(log_file),
                "model": model,
                "max_turns": max_turns,
                "enable_subagent": enable_subagent,
                "checkpoint_enabled": checkpoint_enabled,
                "start_turn": start_turn,
            },
        },
    )

    try:
        final_response, stats = await run_coding_agent(
            task=task,
            workdir=workdir,
            settings=settings,
            model=model,
            max_turns=max_turns,
            max_tokens=max_tokens,
            context_window_tokens=context_window_tokens,
            max_cost_usd=max_cost_usd,
            run_id=run_id,
            enable_subagent=enable_subagent,
            context=context,
            stats=stats,
            start_turn=start_turn,
            start_sha=start_sha,
            checkpoint_enabled=checkpoint_enabled,
            trace_metadata=trace_metadata or None,
            trace_tags=trace_tags or None,
        )
    except MaxTurnsExceeded as exc:
        logger.error(
            "运行失败: %s",
            exc,
            extra={"event": "run.max_turns_exceeded", "trace": trace},
        )
        log_stats(exc.stats, trace=trace)
        log_cost(exc.stats, settings, trace=trace)
        logger.error(
            "可使用 --rollback %s 恢复任务开始前的文件状态。",
            run_id,
            extra={"event": "run.rollback_available", "trace": trace},
        )
        return
    except CostLimitExceeded as exc:
        logger.error(
            "运行因费用上限停止: %s",
            exc,
            extra={"event": "run.cost_limit_exceeded", "trace": trace},
        )
        log_stats(exc.stats, trace=trace)
        log_cost(exc.stats, settings, trace=trace)
        logger.error(
            "可使用 --rollback %s 恢复任务开始前的文件状态。",
            run_id,
            extra={"event": "run.rollback_available", "trace": trace},
        )
        return
    except APIError as exc:
        logger.error(
            "模型请求失败: %s",
            exc,
            extra={"event": "run.api_error", "trace": trace},
        )
        logger.error(
            "可使用 --rollback %s 恢复任务开始前的文件状态。",
            run_id,
            extra={"event": "run.rollback_available", "trace": trace},
        )
        return

    log_stats(stats, trace=trace)
    log_cost(stats, settings, trace=trace)
    if stats.trace_url:
        logger.info(
            "Langfuse Trace URL: %s",
            stats.trace_url,
            extra={
                "event": "run.trace_url",
                "trace": trace,
                "data": {"url": stats.trace_url},
            },
        )
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
