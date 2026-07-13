from __future__ import annotations

import sys

from agent_sdk import extract_text, get_client, load_config


def main() -> None:
    config = load_config()
    model = config.model

    system_prompt = "你是一个简洁、准确的中文助理。"
    user_message = " ".join(sys.argv[1:]).strip() or "请用三句话解释什么是 count_tokens。"
    max_tokens = 200

    messages = [
        {"role": "user", "content": user_message},
    ]

    client = get_client(config)

    # 预估规则不是“按字符数除以 4”这种土办法，而是让服务端用模型的真实分词规则
    # 计算当前请求体大概会占多少输入 token。这里算的是将要发送的 system + messages。
    token_count = client.messages.count_tokens(
        model=model,
        system=system_prompt,
        messages=messages,
    )

    response = client.messages.create(
        model=model,
        system=system_prompt,
        messages=messages,
        max_tokens=max_tokens,
    )

    print("=== Request ===")
    print(f"model: {model}")
    print(f"system: {system_prompt}")
    print(f"messages: {messages}")
    print(f"max_tokens: {max_tokens}")
    print()

    print("=== Estimated Input Tokens ===")
    print(f"count_tokens.input_tokens: {token_count.input_tokens}")
    print()

    print("=== Actual Response ===")
    print(extract_text(response))
    print()

    print("=== Actual Usage ===")
    print(
        f"usage.input_tokens: {getattr(response.usage, 'input_tokens', None)}")
    print(
        f"usage.output_tokens: {getattr(response.usage, 'output_tokens', None)}")
    print(f"stop_reason: {response.stop_reason}")
    print()

    print("=== Notes ===")
    print("1. count_tokens 是发送前预估，只看输入。")
    print("2. usage.input_tokens 是发送后结算。")
    print("3. token 不是字符数，也不是单词数，而是模型 tokenizer 切出来的片段数。")
    print("4. system、messages、role、content，以及协议开销，都会影响 input_tokens。")
    print("5. 两者通常接近，但真正用于记账和统计时要以 usage 为准。")


if __name__ == "__main__":
    main()
