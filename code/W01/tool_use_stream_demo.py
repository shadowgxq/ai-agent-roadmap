from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from anthropic import Anthropic

sys.path.append(str(Path(__file__).resolve().parent.parent / "shared"))

from agent_sdk import (  # noqa: E402
    extract_assistant_blocks,
    extract_text,
    fmt_usage,
    get_client,
    load_config,
)


def get_weather(location: str) -> dict[str, Any]:
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


def print_event(event: object) -> None:
    event_type = getattr(event, "type", "unknown")
    print(f"[event] type={event_type}")

    if event_type == "message_start":
        message = getattr(event, "message", None)
        print(f"  usage={fmt_usage(getattr(message, 'usage', None))}")
        return

    if event_type == "content_block_start":
        index = getattr(event, "index", None)
        content_block = getattr(event, "content_block", None)
        block_type = getattr(content_block, "type", None)
        print(f"  index={index} block_type={block_type}")
        if block_type == "tool_use":
            print(f"  tool_name={getattr(content_block, 'name', None)}")
            print(f"  tool_use_id={getattr(content_block, 'id', None)}")
        return

    if event_type == "content_block_delta":
        index = getattr(event, "index", None)
        delta = getattr(event, "delta", None)
        delta_type = getattr(delta, "type", None)
        print(f"  index={index} delta_type={delta_type}")

        text = getattr(delta, "text", None)
        partial_json = getattr(delta, "partial_json", None)
        thinking = getattr(delta, "thinking", None)

        if text is not None:
            print(f"  delta.text={text!r}")
        if partial_json is not None:
            print(f"  delta.partial_json={partial_json!r}")
        if thinking is not None:
            print(f"  delta.thinking={thinking!r}")
        return

    if event_type == "content_block_stop":
        print(f"  index={getattr(event, 'index', None)}")
        return

    if event_type == "message_delta":
        delta = getattr(event, "delta", None)
        print(f"  stop_reason={getattr(delta, 'stop_reason', None)}")
        print(f"  usage={fmt_usage(getattr(event, 'usage', None))}")
        return

    if event_type == "message_stop":
        print("  message complete")
        return

    if event_type == "ping":
        print("  keep-alive")
        return

    if event_type == "error":
        print(f"  error={getattr(event, 'error', None)}")
        return

    print(f"  raw={event}")


def stream_one_round(
    *,
    client: Anthropic,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> Any:
    with client.messages.stream(
        model=model,
        system=system_prompt,
        messages=messages,
        tools=TOOLS,
        max_tokens=max_tokens,
    ) as stream:
        for event in stream:
            print_event(event)
        return stream.get_final_message()


def main() -> None:
    config = load_config()
    base_url = config.base_url
    model = config.model

    system_prompt = (
        "你是一个会调用工具的中文助理。"
        "当用户询问天气时，优先调用 get_weather，不要假设天气。"
    )
    user_message = " ".join(sys.argv[1:]).strip() or "深圳今天天气怎么样？再给我一句出行建议。"
    max_tokens = 300

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]

    client = get_client(config)

    print("=== Request ===")
    print(f"base_url: {base_url}")
    print(f"model: {model}")
    print(f"system: {system_prompt}")
    print(f"user: {user_message}")
    print(f"tools: {[tool['name'] for tool in TOOLS]}")
    print()

    round_no = 1
    while True:
        print(f"=== Round {round_no}: stream model call ===")
        final_message = stream_one_round(
            client=client,
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        )

        messages.append(
            {
                "role": "assistant",
                "content": extract_assistant_blocks(final_message),
            }
        )

        print()
        print("=== Round Summary ===")
        print(f"stop_reason: {final_message.stop_reason}")
        print(f"usage.input_tokens: {getattr(final_message.usage, 'input_tokens', None)}")
        print(f"usage.output_tokens: {getattr(final_message.usage, 'output_tokens', None)}")

        if final_message.stop_reason != "tool_use":
            print()
            print("=== Final Answer ===")
            print(extract_text(final_message))
            break

        tool_results: list[dict[str, Any]] = []
        print()
        print("=== Local Tool Execution ===")
        for block in final_message.content:
            if block.type != "tool_use":
                continue

            print(f"tool_use.id: {block.id}")
            print(f"tool_use.name: {block.name}")
            print(f"tool_use.input: {json.dumps(block.input, ensure_ascii=False)}")

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
