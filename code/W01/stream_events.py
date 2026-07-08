from __future__ import annotations

import os
import sys
from pathlib import Path

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


def fmt_usage(usage: object | None) -> str:
    if usage is None:
        return "-"

    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    cache_creation_input_tokens = getattr(
        usage, "cache_creation_input_tokens", None)
    cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", None)

    return (
        f"input={input_tokens}, "
        f"output={output_tokens}, "
        f"cache_create={cache_creation_input_tokens}, "
        f"cache_read={cache_read_input_tokens}"
    )


def main() -> None:
    load_env()

    api_key = require_env("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL",
                         "https://api.deepseek.com/anthropic")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    system_prompt = "你是一个简洁、准确的中文助理。"
    user_message = " ".join(sys.argv[1:]).strip() or "请用三句话解释什么是 streaming。"
    max_tokens = 200

    messages = [
        {"role": "user", "content": user_message},
    ]

    print("=== Request ===")
    print(f"base_url: {base_url}")
    print(f"model: {model}")
    print(f"system: {system_prompt}")
    print(f"user: {user_message}")
    print(f"max_tokens: {max_tokens}")
    print(f"messages: {messages}")
    print()

    client = Anthropic(api_key=api_key, base_url=base_url)

    print("=== Events ===")
    with client.messages.stream(
        model=model,
        system=system_prompt,
        messages=messages,
        max_tokens=max_tokens,
    ) as stream:
        for event in stream.text_stream:
            print(event, end="", flush=True)
        final_message = stream.get_final_message()

    print()
    print("=== Final Message ===")
    reply_parts = []
    for block in final_message.content:
        if block.type == "text":
            reply_parts.append(block.text)
    print("".join(reply_parts))
    print()
    print("=== Final Fields ===")
    print(
        f"usage.input_tokens: {getattr(final_message.usage, 'input_tokens', None)}")
    print(
        f"usage.output_tokens: {getattr(final_message.usage, 'output_tokens', None)}")
    print(
        f"usage.total_tokens: {getattr(final_message.usage, 'total_tokens', None)}")
    print(f"stop_reason: {final_message.stop_reason}")


if __name__ == "__main__":
    main()
