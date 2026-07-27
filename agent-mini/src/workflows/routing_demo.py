"""运行一次真实模型驱动的 Routing Workflow。"""

import argparse
import asyncio

from openai import AsyncOpenAI

from ..agent.config import AgentSettings
from .routing import RoutingState, run_routing
from .runtime import WorkflowRuntime


def parse_args() -> argparse.Namespace:
    """解析 Routing Workflow 演示参数。"""
    parser = argparse.ArgumentParser(
        description="运行 router -> selected handler Workflow"
    )
    parser.add_argument("task", help="要分类并处理的任务")
    parser.add_argument("--model", help="覆盖环境配置中的模型")
    parser.add_argument(
        "--max-parse-attempts",
        type=int,
        default=2,
        help="Router 结构化结果的最大解析尝试次数，默认 2",
    )
    return parser.parse_args()


async def main() -> None:
    """组装模型客户端，运行 Routing 并打印状态与用量。"""
    args = parse_args()
    settings = AgentSettings()
    state = RoutingState(task=args.task)
    runtime: WorkflowRuntime | None = None

    try:
        async with AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=2,
        ) as client:
            runtime = WorkflowRuntime(
                client,
                model=args.model or settings.model,
            )
            await run_routing(
                runtime,
                state,
                max_parse_attempts=args.max_parse_attempts,
            )
    finally:
        print(state.model_dump_json(indent=2))
        if runtime is not None:
            print(
                f"模型调用: {runtime.stats.calls}, "
                f"总 token: {runtime.stats.total_tokens}"
            )


if __name__ == "__main__":
    asyncio.run(main())
