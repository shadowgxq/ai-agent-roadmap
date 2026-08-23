"""agent-mini 的命令行入口。"""

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai import APIError


from .agent.checkpoint import load_checkpoint
from .agent.config import AgentSettings
from .agent.context import Context
from .agent.cost import CostCalculator
from .agent.git_snapshot import GitSnapshotError, rollback_to_sha
from .agent.loop import (
    AgentEventName,
    CostLimitExceeded,
    MaxTurnsExceeded,
    RunStats,
)
from .agent.logging_events import (
    build_cost_event_data,
    build_cost_data,
    build_run_started_data,
    build_run_usage_data,
    log_event,
)
from .agent.runtime import run_coding_agent
from .agent.logging_config import (
    CONSOLE_EVENT_NAMES,
    configure_logging,
    get_logger,
)


logger = get_logger("cli")


def _preview_event(value: Any, limit: int = 500) -> str:
    """把事件内容压缩成适合终端阅读的一段文本。"""
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\x00", "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated, total={len(text)} chars]"


def render_agent_event(event: AgentEventName, data: dict[str, Any]) -> None:
    """CLI Adapter：把 Agent Event 转成终端输出，不让 Loop 直接 print。"""
    if event == "text":
        text = data.get("text")
        if isinstance(text, str) and text:
            print(text)
        return

    if event == "tool_call":
        calls = data.get("calls")
        if isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict):
                    print(
                        f"[tool] {call.get('name', '<unknown>')} "
                        f"args={_preview_event(call.get('arguments', '{}'))}"
                    )
        return

    if event == "tool_result":
        results = data.get("results")
        if isinstance(results, list):
            for result in results:
                if isinstance(result, dict):
                    print(
                        f"[tool-result] {result.get('tool_use_id', '<unknown>')}: "
                        f"{_preview_event(result.get('content', ''))}"
                    )
        return

    if event == "diff":
        files = data.get("files")
        if isinstance(files, list):
            for file in files:
                if isinstance(file, dict):
                    print(
                        f"[diff] {file.get('status', 'modified')} "
                        f"{file.get('path', '<unknown>')} "
                        f"(+{file.get('additions', 0)}/-{file.get('deletions', 0)})"
                    )
        return

    if event == "context_usage":
        context_tokens = data.get("context_tokens", "unknown")
        context_window = data.get("context_window_tokens", "unknown")
        print(f"[context] {context_tokens}/{context_window} tokens")
        return

    if event == "done":
        print(f"[agent] {data.get('status', 'completed')}")


def confirm_command(command: str, reason: str) -> bool:
    """在 CLI 中对需要确认的 Shell 命令阻塞等待用户决定。"""
    try:
        answer = input(
            f"\n命令需要确认：{command}\n"
            f"原因：{reason}\n"
            "继续执行？[y/N] "
        )
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


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
        "--router",
        choices=("on", "off"),
        default=None,
        help="覆盖任务分流开关；on 先用 Router 判断 simple/complex。",
    )
    parser.add_argument(
        "--cache",
        choices=("on", "off"),
        default=None,
        help="覆盖 Prompt Cache 开关；不传则使用环境配置。",
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
        help="JSONL 运行日志；默认 logs/agent.jsonl，按运行追加写入。",
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
        or args.router is not None
        or args.cache is not None
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
        or args.router is not None
        or args.cache is not None
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
    data = build_run_usage_data(stats)
    main_data = data["main"]
    subagent_data = data["subagents"]
    total_data = data["total"]
    log_event(
        logger,
        logging.INFO,
        (
            "运行统计: main_turns=%s, subagent_runs=%s, "
            "subagent_turns=%s, compact_calls=%s, compact_tokens=%s, "
            "main_tokens=%s, "
            "subagent_tokens=%s, total_tokens=%s"
        ),
        stats.turns,
        len(stats.subagent_runs),
        subagent_data["turns"],
        main_data["compact_calls"],
        main_data["compact_tokens"],
        main_data["total_tokens"],
        subagent_data["total_tokens"],
        total_data["total_tokens"],
        event="run.usage",
        trace=trace,
        data=data,
    )


def log_cost(
    stats: RunStats,
    cost_calculator: CostCalculator,
    *,
    trace: dict[str, str] | None = None,
) -> None:
    """输出统一成本明细，同时保留历史平铺字段。"""
    cost = cost_calculator.breakdown(stats)
    data = build_cost_data(cost, include_legacy=True)
    if not cost.available:
        log_event(
            logger,
            logging.INFO,
            "预估费用: 未配置完整的模型单价",
            event="run.cost_unavailable",
            trace=trace,
            data=data,
        )
        return
    log_event(
        logger,
        logging.INFO,
        "预估费用: %s %.6f",
        cost.currency,
        cost.total_usd or 0.0,
        event="run.cost",
        trace=trace,
        data=build_cost_event_data(cost),
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
    cost_calculator = CostCalculator.from_settings(settings)

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
        session_id = checkpoint.session_id
        message_id = checkpoint.message_id
        enable_subagent = checkpoint.enable_subagent
        router_enabled = checkpoint.router_enabled
        prompt_cache_enabled = checkpoint.prompt_cache_enabled
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
        model = args.model or settings.main_model_name
        max_turns = args.max_turns or settings.max_turns
        max_tokens = 3000
        context_window_tokens = settings.context_window_tokens
        max_cost_usd = None
        session_id = None
        message_id = None
        enable_subagent = args.enable_subagent
        router_enabled = (
            settings.router_enabled
            if args.router is None
            else args.router == "on"
        )
        prompt_cache_enabled = (
            settings.prompt_cache_enabled
            if args.cache is None
            else args.cache == "on"
        )
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
    # 这些运行日志仍然会写入 JSONL；终端展示交给下面的 Agent Event
    # Renderer，避免同一份回答/工具结果同时由两条通道重复输出。
    cli_log_events = CONSOLE_EVENT_NAMES - {
        "llm.completed",
        "tool.completed",
        "agent.final_answer",
        "agent.completed",
    }
    log_file = configure_logging(
        args.log_file or settings.log_file,
        console_event_names=cli_log_events,
    )
    log_event(
        logger,
        logging.INFO,
        "[RUN] %s",
        log_file,
        event="run.resumed" if args.resume else "run.started",
        trace=trace,
        console_message=f"[RUN] {task}",
        data=build_run_started_data(
            task=task,
            workdir=workdir,
            model=model,
            main_model=settings.main_model_name,
            small_model=settings.small_model_name,
            router_model=(
                settings.router_model_name if router_enabled else None
            ),
            router_enabled=router_enabled,
            prompt_cache_enabled=prompt_cache_enabled,
            prompt_cache_key=settings.prompt_cache_key,
            prompt_cache_retention=settings.prompt_cache_retention,
            max_turns=max_turns,
            start_turn=start_turn,
            additional={
                "log_file": str(log_file),
                "enable_subagent": enable_subagent,
                "checkpoint_enabled": checkpoint_enabled,
            },
        ),
    )

    try:
        _, stats = await run_coding_agent(
            task=task,
            workdir=workdir,
            settings=settings,
            cost_calculator=cost_calculator,
            model=model,
            router_enabled=router_enabled,
            prompt_cache_enabled=prompt_cache_enabled,
            max_turns=max_turns,
            max_tokens=max_tokens,
            context_window_tokens=context_window_tokens,
            max_cost_usd=max_cost_usd,
            run_id=run_id,
            session_id=session_id,
            message_id=message_id,
            enable_subagent=enable_subagent,
            context=context,
            stats=stats,
            start_turn=start_turn,
            start_sha=start_sha,
            checkpoint_enabled=checkpoint_enabled,
            event_callback=render_agent_event,
            on_confirm=confirm_command,
            trace_metadata=trace_metadata or None,
            trace_tags=trace_tags or None,
            log_start=False,
        )
    except MaxTurnsExceeded as exc:
        log_stats(exc.stats, trace=trace)
        log_cost(exc.stats, cost_calculator, trace=trace)
        return
    except CostLimitExceeded as exc:
        log_stats(exc.stats, trace=trace)
        log_cost(exc.stats, cost_calculator, trace=trace)
        return
    except APIError:
        return
    except Exception:
        raise

    log_stats(stats, trace=trace)
    log_cost(stats, cost_calculator, trace=trace)
    if stats.trace_url:
        log_event(
            logger,
            logging.INFO,
            "Langfuse Trace URL: %s",
            stats.trace_url,
            event="run.trace_url",
            trace=trace,
            data={"url": stats.trace_url},
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_event(
            logger,
            logging.WARNING,
            "运行已由用户中断。",
            event="run.interrupted",
        )
