from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv


def load_env() -> None:
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


def get_weather(location: str) -> dict[str, Any]:
    """本地 fake tool，只为演示 tool_use -> tool_result 闭环。"""
    weather_map = {
        "北京": {"condition": "晴", "temperature_c": 31},
        "上海": {"condition": "多云", "temperature_c": 29},
        "深圳": {"condition": "小雨", "temperature_c": 27},
    }
    data = weather_map.get(location, {"condition": "未知", "temperature_c": 25})
    return {
        "location": location,
        "source": "local-demo-tool",
        **data,
    }


TOOLS = [
    {
        "name": "get_weather",
        "description": "查询某个城市的天气。仅支持北京、上海、深圳，其他城市返回默认值。",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "要查询天气的城市名，例如 北京",
                }
            },
            "required": ["location"],
        },
    }
]


def run_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    if name == "get_weather":
        location = str(tool_input.get("location", "")).strip()
        if not location:
            raise ValueError("tool input 缺少 location")
        return get_weather(location)

    raise ValueError(f"未知工具: {name}")


def extract_text(response: Any) -> str:
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def main() -> None:
    load_env()

    api_key = require_env("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL",
                         "https://api.deepseek.com/anthropic")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    system_prompt = (
        "你是一个会调用工具的中文助理。"
        "当用户询问天气时，优先调用 get_weather，不要假设天气。"
    )
    user_message = " ".join(sys.argv[1:]).strip() or "北京今天天气怎么样？顺便给我一句出行建议。"
    max_tokens = 300

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]

    client = Anthropic(api_key=api_key, base_url=base_url)

    round_no = 1
    while True:
        print(f"=== Round {round_no}: model call ===")
        response = client.messages.create(
            model=model,
            system=system_prompt,
            messages=messages,
            tools=TOOLS,
            max_tokens=max_tokens,
        )

        assistant_blocks: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                assistant_blocks.append(
                    {
                        "type": "text",
                        "text": block.text,
                    }
                )
            elif block.type == "tool_use":
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        messages.append(
            {
                "role": "assistant",
                "content": assistant_blocks,
            }
        )

        print(f"stop_reason: {response.stop_reason}")
        print(
            f"usage.input_tokens: {getattr(response.usage, 'input_tokens', None)}")
        print(
            f"usage.output_tokens: {getattr(response.usage, 'output_tokens', None)}")

        if response.stop_reason != "tool_use":
            print()
            print("=== Final Answer ===")
            print(extract_text(response))
            break

        tool_results: list[dict[str, Any]] = []
        print()
        print("=== Local Tool Execution ===")
        for block in response.content:
            if block.type != "tool_use":
                continue

            print(f"tool_use.id: {block.id}")
            print(f"tool_use.name: {block.name}")
            print(
                f"tool_use.input: {json.dumps(block.input, ensure_ascii=False)}")

            try:
                result = run_tool(block.name, block.input)
                is_error = False
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
                is_error = True

            print(f"tool_result: {json.dumps(result, ensure_ascii=False)}")

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                    "is_error": is_error,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": tool_results,
            }
        )
        print()
        round_no += 1


if __name__ == "__main__":
    main()
