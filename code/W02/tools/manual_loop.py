from __future__ import annotations

import json
import sys
from typing import Any

from agent_sdk import extract_text, get_client, load_config


def get_weather(city: str) -> dict[str, Any]:
    """本地 mock 工具：直接返回假数据，不访问真实天气 API。"""
    fake_weather = {
        "北京": {"temperature": 26, "condition": "晴"},
        "上海": {"temperature": 24, "condition": "多云"},
        "深圳": {"temperature": 28, "condition": "小雨"},
    }
    return {
        "city": city,
        **fake_weather.get(city, {"temperature": 25, "condition": "未知"}),
        "source": "local-mock",
    }


TOOLS = [
    {
        "name": "get_weather",
        "description": "查询指定城市今天的天气。只能查询当前天气，不能预测未来天气。",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，例如北京、上海、深圳。",
                }
            },
            "required": ["city"],
        },
    }
]


def print_messages(title: str, messages: list[dict[str, Any]]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(messages, ensure_ascii=False, indent=2))


def assistant_content(response: Any) -> list[dict[str, Any]]:
    """把 SDK 的 assistant content block 转成下一次请求可发送的字典。"""
    blocks: list[dict[str, Any]] = []
    for block in response.content:
        if block.type == "text":
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return blocks


def main() -> None:
    config = load_config()
    client = get_client(config)
    user_message = (
        " ".join(sys.argv[1:]).strip() or "北京今天多少度？请告诉我天气情况。"
    )
    system_prompt = (
        "你是一个中文助理。用户询问天气时，必须调用 get_weather，"
        "不能直接猜测天气。"
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]

    response = client.messages.create(
        model=config.model,
        system=system_prompt,
        messages=messages,
        tools=TOOLS,
        max_tokens=3000,
    )
    print(f"stop_reason: {response.stop_reason}")

    assistant_blocks = assistant_content(response)
    messages.append({"role": "assistant", "content": assistant_blocks})

    tool_use_blocks = [
        block for block in response.content
        if block.type == "tool_use"
    ]
    if response.stop_reason != "tool_use" or not tool_use_blocks:
        raise RuntimeError("模型没有返回预期的 tool_use block")

    tool_use = tool_use_blocks[0]

    # 本地执行工具，再手工构造 tool_result。
    tool_input = tool_use.input
    tool_result = get_weather(str(tool_input["city"]))
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            ],
        }
    )
    print_messages("Request 2: after local tool_result", messages)

    # 第二次请求：模型读取 tool_result，生成自然语言回答。
    final_response = client.messages.create(
        model=config.model,
        system=system_prompt,
        messages=messages,
        tools=TOOLS,
        max_tokens=300,
    )
    messages.append(
        {"role": "assistant", "content": assistant_content(final_response)}
    )
    print(extract_text(final_response))


if __name__ == "__main__":
    main()
