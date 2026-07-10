from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "shared"))

from agent_sdk import fmt_usage, get_client, load_config  # noqa: E402


def main() -> None:
    config = load_config()
    base_url = config.base_url
    model = config.model

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

    client = get_client(config)

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
