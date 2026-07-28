"""运行一次真实模型驱动的 Parallelization Workflow。"""

import argparse
import asyncio

from openai import AsyncOpenAI

from ..agent.config import AgentSettings
from .parallelization import (
    ParallelizationState,
    VotingState,
    run_parallelization,
    run_voting,
)
from .runtime import WorkflowRuntime


def parse_args() -> argparse.Namespace:
    """解析 Parallelization Workflow 演示参数。"""
    parser = argparse.ArgumentParser(
        description="运行 Sectioning 或 Voting Parallelization Workflow"
    )
    parser.add_argument("task", help="要并行处理或投票判断的任务")
    parser.add_argument("--model", help="覆盖环境配置中的模型")
    parser.add_argument(
        "--mode",
        choices=("sectioning", "voting"),
        default="sectioning",
        help="并行模式，默认 sectioning",
    )
    parser.add_argument(
        "--worker-max-tokens",
        type=int,
        default=1200,
        help="每个 Worker 的最大输出 token，默认 1200",
    )
    parser.add_argument(
        "--aggregator-max-tokens",
        type=int,
        default=1600,
        help="Aggregator 的最大输出 token，默认 1600",
    )
    parser.add_argument(
        "--voters",
        type=int,
        default=3,
        help="Voting 模式的 Voter 数量，必须是大于等于 3 的奇数",
    )
    parser.add_argument(
        "--max-parse-attempts",
        type=int,
        default=2,
        help="每个 Voter 的最大结构化解析尝试次数，默认 2",
    )
    return parser.parse_args()


async def main() -> None:
    """组装模型客户端，运行并行评审并打印状态与用量。"""
    args = parse_args()
    settings = AgentSettings()
    if args.mode == "sectioning":
        state = ParallelizationState(task=args.task)
    else:
        state = VotingState(task=args.task)
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
            if isinstance(state, ParallelizationState):
                await run_parallelization(
                    runtime,
                    state,
                    worker_max_tokens=args.worker_max_tokens,
                    aggregator_max_tokens=args.aggregator_max_tokens,
                )
            else:
                await run_voting(
                    runtime,
                    state,
                    voter_count=args.voters,
                    voter_max_tokens=args.worker_max_tokens,
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
