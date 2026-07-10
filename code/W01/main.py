from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "shared"))

from agent_sdk import extract_text, get_client, load_config  # noqa: E402


def main() -> None:
    config = load_config()
    base_url = config.base_url
    model = config.model

    system_prompt = "你是一个简洁、准确的中文助理。"
    user_message = " ".join(sys.argv[1:]).strip() or "请用三句话解释什么是 Messages API。"
    max_tokens = 200

    # 这里统一切到 Anthropic Messages API 风格：
    # - messages: 只放 user / assistant 历史
    # - system: 顶层独立参数
    # - max_tokens: 输出上限
    # - usage: token 统计
    # - stop_reason: 停止原因
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
    response = client.messages.create(
        model=model,
        system=system_prompt,
        messages=messages,
        max_tokens=max_tokens,
    )

    reply = extract_text(response)
    usage = response.usage

    print("=== Response ===")
    print(reply)
    print()
    print("=== Key Fields ===")
    print(f"usage.input_tokens: {getattr(usage, 'input_tokens', None)}")
    print(f"usage.output_tokens: {getattr(usage, 'output_tokens', None)}")
    print(f"usage.total_tokens: {getattr(usage, 'total_tokens', None)}")
    print(f"stop_reason: {response.stop_reason}")


if __name__ == "__main__":
    main()
