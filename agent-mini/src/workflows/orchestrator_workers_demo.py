"""运行一次真实模型驱动的 Orchestrator-Workers Workflow。"""

import argparse
import asyncio

from openai import AsyncOpenAI

from ..agent.config import AgentSettings
from .orchestrator_workers import (
    OrchestratorState,
    run_orchestrator_workers,
)
from .runtime import WorkflowRuntime


def parse_args() -> argparse.Namespace:
    """解析 Orchestrator-Workers 演示参数。"""
    parser = argparse.ArgumentParser(
        description="运行 orchestrator -> workers -> synthesizer Workflow"
    )
    parser.add_argument("task", help="要动态拆分并处理的复杂任务")
    parser.add_argument("--model", help="覆盖环境配置中的模型")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=5,
        help="Orchestrator 最多可以生成的 Worker 数量，默认 5",
    )
    parser.add_argument(
        "--max-parse-attempts",
        type=int,
        default=2,
        help="Orchestrator 的最大结构化解析尝试次数，默认 2",
    )
    parser.add_argument(
        "--orchestrator-max-tokens",
        type=int,
        default=1200,
        help="Orchestrator 的最大输出 token，默认 1200",
    )
    parser.add_argument(
        "--worker-max-tokens",
        type=int,
        default=1600,
        help="每个 Worker 的最大输出 token，默认 1600",
    )
    parser.add_argument(
        "--synthesizer-max-tokens",
        type=int,
        default=2000,
        help="Synthesizer 的最大输出 token，默认 2000",
    )
    return parser.parse_args()


async def main() -> None:
    """组装客户端，运行完整 Workflow 并打印状态与用量。"""
    args = parse_args()
    settings = AgentSettings()
    state = OrchestratorState(task=args.task)
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
            await run_orchestrator_workers(
                runtime,
                state,
                max_workers=args.max_workers,
                orchestrator_max_tokens=args.orchestrator_max_tokens,
                worker_max_tokens=args.worker_max_tokens,
                synthesizer_max_tokens=args.synthesizer_max_tokens,
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
