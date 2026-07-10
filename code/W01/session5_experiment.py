from __future__ import annotations

import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from pricing import calc_cost


ROOT = Path(__file__).parent
ENV_PATH = ROOT.parent.parent / ".env"
NOTES_PATH = ROOT / "NOTES.md"


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


def run() -> list[dict[str, int | float | str | None]]:
    load_dotenv(ENV_PATH)
    api_key = require_env("ANTHROPIC_API_KEY")
    base_url = os.getenv(
        "ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    system_prompt = "你是一个简洁的中文助理。每次只用一句话回答。"
    max_tokens = 80
    messages: list[dict[str, str]] = []
    cumulative_cost_usd = 0.0
    rows: list[dict[str, int | float | str | None]] = []
    client = Anthropic(api_key=api_key, base_url=base_url)

    for round_number in range(1, 11):
        user_message = (
            f"这是第 {round_number} 轮。请记住我正在做 token 增长实验，"
            "并用一句话说明你知道了。"
        )
        request_messages = [
            *messages,
            {"role": "user", "content": user_message},
        ]

        estimate = client.messages.count_tokens(
            model=model,
            system=system_prompt,
            messages=request_messages,
        )
        response = client.messages.create(
            model=model,
            system=system_prompt,
            messages=request_messages,
            max_tokens=max_tokens,
        )

        input_tokens = getattr(response.usage, "input_tokens", None)
        output_tokens = getattr(response.usage, "output_tokens", None)
        cache_read_input_tokens = getattr(
            response.usage, "cache_read_input_tokens", None
        )
        total_input_tokens = (input_tokens or 0) + (
            cache_read_input_tokens or 0
        )
        round_cost_usd = calc_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        )
        cumulative_cost_usd += round_cost_usd
        assistant_message = extract_text(response)

        rows.append(
            {
                "round": round_number,
                "estimated_input_tokens": getattr(estimate, "input_tokens", None),
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
                "total_input_tokens": total_input_tokens,
                "output_tokens": output_tokens,
                "round_cost_usd": round_cost_usd,
                "cumulative_cost_usd": cumulative_cost_usd,
                "stop_reason": getattr(response, "stop_reason", None),
            }
        )
        messages.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
        )

        print(
            f"round={round_number} "
            f"estimated_input={getattr(estimate, 'input_tokens', None)} "
            f"input={input_tokens} cache_read={cache_read_input_tokens} "
            f"total_input={total_input_tokens} output={output_tokens} "
            f"round_cost=${round_cost_usd:.8f} "
            f"cumulative=${cumulative_cost_usd:.8f}"
        )

    return rows


def write_notes(rows: list[dict[str, int | float | str | None]]) -> None:
    first_input = rows[0]["total_input_tokens"] or 0
    last_input = rows[-1]["total_input_tokens"] or 0
    ratio = last_input / first_input if first_input else 0
    total_cost = rows[-1]["cumulative_cost_usd"]

    table = [
        "# W01 Session 5 实验记录",
        "",
        "> 运行脚本：`uv run python session5_experiment.py`",
        "> 目标：观察多轮历史重发时 input tokens 的增长，并对比预估值和实际值。",
        "",
        "| 轮次 | count_tokens 预估 | 未缓存 input | cache_read input | 完整 input | output | 本轮费用(USD) | 累计费用(USD) | stop_reason |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for row in rows:
        table.append(
            "| {round} | {estimated_input_tokens} | {input_tokens} | {cache_read_input_tokens} | "
            "{total_input_tokens} | {output_tokens} | ${round_cost_usd:.8f} | "
            "${cumulative_cost_usd:.8f} | {stop_reason} |".format(
                **row
            )
        )

    table.extend(
        [
            "",
            "## 结论",
            "",
            f"- 第 1 轮实际 input tokens：`{first_input}`。",
            f"- 第 10 轮实际 input tokens：`{last_input}`。",
            f"- 第 10 轮约为第 1 轮的 `{ratio:.2f}` 倍。",
            f"- 10 轮累计费用：`${float(total_cost):.8f}`。",
            "- 多轮请求会把此前的 user/assistant history 一起重新发送，所以 input tokens 会增长。",
            "- 发送前用 `count_tokens` 做容量和成本预估，最终记账以响应 `usage` 为准。",
        ]
    )
    NOTES_PATH.write_text("\n".join(table) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_notes(run())
    print(f"已写入: {NOTES_PATH}")
