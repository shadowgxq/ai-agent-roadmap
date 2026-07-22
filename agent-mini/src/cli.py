"""agent-mini 的命令行入口。"""

import argparse
import asyncio
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic


if __package__:
    from .agent.config import AgentSettings
    from .agent.context import Context
    from .agent.loop import run
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
    from agent.loop import run
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

    async with AsyncAnthropic(
        api_key=settings.api_key,
        base_url=settings.base_url,
    ) as client:
        final_response = await run(
            client,
            context,
            registry,
            model=model,
            system_prompt=build_system_prompt(workdir),
            max_turns=max_turns,
            max_tokens=3000,
        )

    print(f"最终 stop_reason: {final_response.stop_reason}")
    print(f"最终回答: {extract_text(final_response)}")


if __name__ == "__main__":
    asyncio.run(main())
