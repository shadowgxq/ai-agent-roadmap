from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv


ROOT = Path(__file__).parent
ENV_PATH = ROOT.parent.parent / ".env"


@dataclass
class Answer:
    question: str
    text: str
    output_tokens: int | None


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


def extract_text(message: object) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", []):
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


async def ask(
    client: AsyncAnthropic,
    model: str,
    question: str,
) -> Answer:
    response = await client.messages.create(
        model=model,
        system="你是一个简洁的中文助理。每次最多用两句话回答。",
        messages=[{"role": "user", "content": question}],
        max_tokens=120,
    )
    return Answer(
        question=question,
        text=extract_text(response),
        output_tokens=getattr(response.usage, "output_tokens", None),
    )


async def run_serial(
    client: AsyncAnthropic,
    model: str,
    questions: list[str],
) -> tuple[list[Answer], float]:
    started_at = time.perf_counter()
    answers: list[Answer] = []
    for question in questions:
        answers.append(await ask(client, model, question))
    return answers, time.perf_counter() - started_at


async def run_parallel(
    client: AsyncAnthropic,
    model: str,
    questions: list[str],
) -> tuple[list[Answer | Exception], float]:
    started_at = time.perf_counter()
    tasks = [ask(client, model, question) for question in questions]

    # gather 会同时调度这些 coroutine，并按传入顺序返回结果。
    # return_exceptions=True 保证单个请求失败时，其他结果仍然可以保留。
    answers = await asyncio.gather(*tasks, return_exceptions=True)
    return answers, time.perf_counter() - started_at


def print_results(title: str, answers: list[Answer | Exception], elapsed: float) -> None:
    print(f"\n=== {title} ===")
    for index, answer in enumerate(answers, start=1):
        if isinstance(answer, Exception):
            print(f"{index}. failed: {type(answer).__name__}: {answer}")
            continue
        print(
            f"{index}. question={answer.question}\n"
            f"   answer={answer.text}\n"
            f"   output_tokens={answer.output_tokens}"
        )
    print(f"elapsed_seconds={elapsed:.2f}")


async def run(questions: list[str]) -> None:
    load_dotenv(ENV_PATH)
    api_key = require_env("ANTHROPIC_API_KEY")
    base_url = os.getenv(
        "ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    async with AsyncAnthropic(api_key=api_key, base_url=base_url) as client:
        serial_answers, serial_elapsed = await run_serial(client, model, questions)
        parallel_answers, parallel_elapsed = await run_parallel(
            client, model, questions
        )

    print_results("serial", serial_answers, serial_elapsed)
    print_results("parallel: asyncio.gather",
                  parallel_answers, parallel_elapsed)
    if parallel_elapsed:
        print(f"speedup={serial_elapsed / parallel_elapsed:.2f}x")
    print("说明：网络延迟相近时，并行耗时应接近单个请求，而不是串行的 3 倍。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="比较 Anthropic API 串行和 gather 并发")
    parser.add_argument(
        "questions",
        nargs="*",
        default=[
            "用一句话解释 asyncio 是什么。",
            "用一句话解释 Pydantic 是什么。",
            "用一句话解释 SSE 是什么。",
        ],
        help="最多建议传入 3 个相互独立的问题",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not 1 <= len(args.questions) <= 3:
        raise SystemExit("questions 数量必须在 1 到 3 之间")
    asyncio.run(run(args.questions))
