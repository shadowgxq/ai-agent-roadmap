import json
from typing import Any
from agent_sdk import extract_text, get_client, load_config


def get_weather(city: str) -> dict[str, Any]:
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


def main() -> None:
    config = load_config()
    client = get_client(config)

    user_message = "北京今天多少度？请告诉我天气情况。"
    system_prompt = "你是一个中文助理。如果用户问天气，必须调用 get_weather 工具。"

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]

    # 第一次请求：让模型决定是否调用工具
    response = client.messages.create(
        model=config.model,
        system=system_prompt,
        messages=messages,
        tools=TOOLS,
        max_tokens=3000,
    )

    # 把 assistant 的 tool_use 消息加入上下文
    messages.append(
        {
            "role": "assistant",
            "content": [
                block.model_dump(exclude_none=True)
                for block in response.content
            ],
        }
    )

    # 如果模型要求调用工具
    if response.stop_reason == "tool_use":
        for block in response.content:
            if block.type == "tool_use":
                city = block.input["city"]
                tool_result = get_weather(city)

                # 把工具结果返回给模型
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            }
                        ],
                    }
                )

        # 第二次请求：让模型基于工具结果生成最终回答
        final_response = client.messages.create(
            model=config.model,
            system=system_prompt,
            messages=messages,
            tools=TOOLS,
            max_tokens=300,
        )

        print(extract_text(final_response))

    else:
        # 如果模型没有调用工具，直接打印第一次回答
        print(extract_text(response))


if __name__ == "__main__":
    main()
