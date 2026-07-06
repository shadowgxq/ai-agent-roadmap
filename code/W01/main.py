from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def load_env() -> None:
    """从仓库根目录加载 .env，保持和 test_api.py 一致。"""
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


def main() -> None:
    load_env()

    api_key = require_env("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    system_prompt = "你是一个简洁、准确的中文助理。"
    user_message = " ".join(sys.argv[1:]).strip() or "请用三句话解释什么是 Messages API。"
    max_tokens = 200

    # 这里沿用当前仓库已经接好的 OpenAI-compatible 接口。
    # 概念上对应你在 W01 要理解的几个字段：
    # - messages: 对话历史
    # - system: 在 OpenAI-compatible 接口里通常作为 system role 放进 messages；
    #           Anthropic Messages API 则是顶层独立参数
    # - max_tokens: 输出上限
    # - usage: token 统计
    # - stop_reason: 这里的兼容字段名通常叫 finish_reason
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

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.7,
    )

    choice = response.choices[0]
    reply = choice.message.content or ""
    usage = response.usage

    print("=== Response ===")
    print(reply)
    print()
    print("=== Key Fields ===")
    print(f"usage.input_tokens: {getattr(usage, 'prompt_tokens', None)}")
    print(f"usage.output_tokens: {getattr(usage, 'completion_tokens', None)}")
    print(f"usage.total_tokens: {getattr(usage, 'total_tokens', None)}")
    print(f"stop_reason(兼容字段 finish_reason): {choice.finish_reason}")


if __name__ == "__main__":
    main()
