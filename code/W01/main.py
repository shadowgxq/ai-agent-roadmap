from __future__ import annotations

import sys

from agent_sdk import (
    extract_chat_text,
    fmt_chat_usage,
    get_codex_client,
    load_codex_config,
)


def main() -> None:
    config = load_codex_config()
    base_url = config.base_url
    model = config.model

    system_prompt = "你是一个简洁、准确的中文助理。"
    user_message = " ".join(sys.argv[1:]).strip() or "请用三句话解释什么是 Messages API。"
    max_tokens = 200

    # 这里使用 OpenAI-compatible Chat Completions 风格：
    # - system: 作为 messages 的一条 system 消息
    # - messages: 保存完整的对话历史
    # - max_tokens: 输出上限
    # - usage: token 统计
    # - finish_reason: 停止原因
    messages = [
        {"role": "system", "content": system_prompt},
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

    client = get_codex_client(config)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )

    reply = extract_chat_text(response)
    usage = response.usage

    print("=== Response ===")
    print(reply)
    print()
    print("=== Key Fields ===")
    print(f"usage: {fmt_chat_usage(usage)}")
    print(f"finish_reason: {response.choices[0].finish_reason}")


if __name__ == "__main__":
    main()
