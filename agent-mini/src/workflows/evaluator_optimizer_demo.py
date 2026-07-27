"""运行一次真实模型驱动的 Evaluator-Optimizer Workflow。"""

import argparse
import asyncio
from pathlib import Path

from openai import AsyncOpenAI

from ..agent.config import AgentSettings
from .evaluator_optimizer import run_evaluator_optimizer
from .runtime import WorkflowRuntime
from .state import WorkflowState


def parse_args() -> argparse.Namespace:
    """解析 Evaluator-Optimizer 演示参数。"""
    parser = argparse.ArgumentParser(
        description="运行 coder -> reviewer -> optimize Workflow"
    )
    parser.add_argument("task", help="要交给 Workflow 完成的代码任务")
    parser.add_argument("--model", help="覆盖环境配置中的模型")
    parser.add_argument(
        "--initial-code-file",
        type=Path,
        help="先评审指定文件中的已有代码，再根据意见优化",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="最多执行的生成与评审轮数，默认 3",
    )
    return parser.parse_args()


async def main() -> None:
    """组装模型客户端，运行 Workflow 并打印状态与用量。"""
    args = parse_args()
    settings = AgentSettings()
    initial_code = ""
    if args.initial_code_file is not None:
        initial_code = args.initial_code_file.read_text(encoding="utf-8")
        if not initial_code.strip():
            raise ValueError("初始代码文件不能为空")

    state = WorkflowState(task=args.task, code=initial_code)
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
            await run_evaluator_optimizer(
                runtime,
                state,
                max_iterations=args.max_iterations,
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
