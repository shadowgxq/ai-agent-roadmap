"""agent-mini 的命令行入口。"""

import argparse
import asyncio
from pathlib import Path
from typing import Any

from openai import APIError


if __package__:
    from .agent.config import AgentSettings
    from .agent.cost import estimate_cost
    from .agent.loop import MaxTurnsExceeded, RunStats
    from .agent.runtime import run_coding_agent
else:
    from agent.config import AgentSettings
    from agent.cost import estimate_cost
    from agent.loop import MaxTurnsExceeded, RunStats
    from agent.runtime import run_coding_agent


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
    """提取 Chat Completions 响应中的 assistant 文本。"""
    return message.choices[0].message.content or "(模型未返回文本)"


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


def print_cost(stats: RunStats, settings: AgentSettings) -> None:
    """价格配置完整时打印预估费用。"""
    cost = estimate_cost(stats, settings)
    if cost is None:
        print("预估费用: 未配置完整的模型单价")
        return

    print(f"预估费用: {settings.price_currency} {cost:.6f}")


async def main() -> None:
    """解析命令行参数，运行 Agent 并展示结果。"""
    args = parse_args()
    workdir = args.workdir.resolve()
    settings = AgentSettings()

    try:
        final_response, stats = await run_coding_agent(
            task=args.task,
            workdir=workdir,
            settings=settings,
            model=args.model,
            max_turns=args.max_turns,
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
    print(f"最终 finish_reason: {final_response.choices[0].finish_reason}")
    print(f"最终回答: {extract_text(final_response)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n运行已由用户中断。")
