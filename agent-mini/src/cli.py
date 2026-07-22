"""agent-mini 的命令行入口。"""

import argparse
import asyncio
from pathlib import Path
from typing import Any

from anthropic import APIError, AsyncAnthropic


if __package__:
    from .agent.config import AgentSettings
    from .agent.context import Context
    from .agent.loop import MaxTurnsExceeded, RunStats, run
    from .agent.prompts import build_system_prompt
    from .tools import (
        ToolRegistry,
        register_fs_tools,
        register_search_tools,
        register_shell_tools,
    )
else:
    from agent.config import AgentSettings
    from agent.context import Context
    from agent.loop import MaxTurnsExceeded, RunStats, run
    from agent.prompts import build_system_prompt
    from tools import (
        ToolRegistry,
        register_fs_tools,
        register_search_tools,
        register_shell_tools,
    )


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

    args = parser.parse_args()
    if args.max_turns is not None and args.max_turns < 1:
        parser.error("--max-turns 必须大于 0")
    return args


def extract_text(message: Any) -> str:
    """提取模型响应中的文本 block。"""
    text = "".join(
        block.text for block in message.content if block.type == "text"
    )
    return text or "(模型未返回文本)"


def print_stats(stats: RunStats) -> None:
    """打印一次 Agent 运行累计的模型用量。"""
    print(f"总轮数: {stats.turns}")
    print(f"普通输入 token: {stats.input_tokens}")
    print(f"缓存读取 token: {stats.cache_read_input_tokens}")
    print(f"缓存写入 token: {stats.cache_creation_input_tokens}")
    print(f"输出 token: {stats.output_tokens}")
    total_tokens = (
        stats.input_tokens
        + stats.cache_read_input_tokens
        + stats.cache_creation_input_tokens
        + stats.output_tokens
    )
    print(f"总 token: {total_tokens}")


def estimate_cost(
    stats: RunStats,
    input_price_per_million: float,
    output_price_per_million: float,
    cache_read_price_per_million: float = 0,
    cache_creation_price_per_million: float = 0,
) -> float:
    """根据 token 用量和每百万 token 单价估算费用。"""
    input_cost = (
        stats.input_tokens / 1_000_000
        * input_price_per_million
    )
    output_cost = (
        stats.output_tokens / 1_000_000
        * output_price_per_million
    )
    cache_read_cost = (
        stats.cache_read_input_tokens / 1_000_000
        * cache_read_price_per_million
    )
    cache_creation_cost = (
        stats.cache_creation_input_tokens / 1_000_000
        * cache_creation_price_per_million
    )
    return input_cost + output_cost + cache_read_cost + cache_creation_cost


def print_cost(stats: RunStats, settings: AgentSettings) -> None:
    """价格配置完整时打印预估费用。"""
    if (
        settings.input_price_per_million is None
        or settings.output_price_per_million is None
    ):
        print("预估费用: 未配置模型单价")
        return

    if (
        stats.cache_read_input_tokens > 0
        and settings.cache_read_price_per_million is None
    ):
        print("预估费用: 检测到缓存读取用量，但未配置缓存读取单价")
        return

    if (
        stats.cache_creation_input_tokens > 0
        and settings.cache_creation_price_per_million is None
    ):
        print("预估费用: 检测到缓存写入用量，但未配置缓存写入单价")
        return

    cost = estimate_cost(
        stats,
        settings.input_price_per_million,
        settings.output_price_per_million,
        settings.cache_read_price_per_million or 0,
        settings.cache_creation_price_per_million or 0,
    )
    print(f"预估费用: {settings.price_currency} {cost:.6f}")


async def main() -> None:
    """解析参数、组装依赖并运行 Agent。"""
    args = parse_args()
    workdir = args.workdir.resolve()
    if not workdir.is_dir():
        raise NotADirectoryError(f"工作目录不存在或不是目录: {workdir}")

    settings = AgentSettings()
    registry = ToolRegistry()
    register_fs_tools(registry, workdir)
    register_search_tools(registry, workdir)
    register_shell_tools(
        registry,
        workdir,
        max_output_chars=settings.max_tool_output_chars,
    )

    context = Context()
    context.append_user(args.task)
    model = args.model or settings.model
    max_turns = args.max_turns or settings.max_turns

    try:
        async with AsyncAnthropic(
            api_key=settings.api_key,
            base_url=settings.base_url,
        ) as client:
            final_response, stats = await run(
                client,
                context,
                registry,
                model=model,
                system_prompt=build_system_prompt(workdir),
                max_turns=max_turns,
                max_tokens=3000,
            )
    except MaxTurnsExceeded as exc:
        print(f"运行失败: {exc}")
        print_stats(exc.stats)
        print_cost(exc.stats, settings)
        return
    except APIError as exc:
        print(f"模型请求失败: {exc}")
        return

    print_stats(stats)
    print_cost(stats, settings)
    print(f"最终 stop_reason: {final_response.stop_reason}")
    print(f"最终回答: {extract_text(final_response)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n运行已由用户中断。")
