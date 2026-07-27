"""运行一次 Prompt Chaining，便于手动观察共享状态。"""

import argparse
import asyncio

from openai import AsyncOpenAI

from ..agent.config import AgentSettings
from .chaining import run_chaining
from .runtime import WorkflowRuntime
from .state import WorkflowState


def parse_args() -> argparse.Namespace:
    """解析 Prompt Chaining 演示参数。"""
    parser = argparse.ArgumentParser(
        description="运行 plan -> gate -> implement -> summarize Workflow"
    )
    parser.add_argument("task", help="要交给 Workflow 处理的任务")
    parser.add_argument("--model", help="覆盖环境配置中的模型")
    parser.add_argument(
        "--plan-max-chars",
        type=int,
        default=6000,
        help="计划允许的最大字符数，默认 6000",
    )
    return parser.parse_args()


async def main() -> None:
    """组装模型客户端，执行 Workflow 并打印最终状态。"""
    args = parse_args()
    settings = AgentSettings()
    state = WorkflowState(task=args.task)
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
            await run_chaining(
                runtime,
                state,
                plan_max_chars=args.plan_max_chars,
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
