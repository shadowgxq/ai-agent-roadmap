import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from pricing import calc_cost


def load_env() -> None:
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


conversation_history: list[dict[str, str]] = []
cumulative_cost_usd = 0.0


def extract_text(message) -> str:
    parts: list[str] = []
    for block in message.content:
        if block.type == "text":
            parts.append(block.text)
    return "".join(parts)


def agentOutput(message: str) -> None:
    global cumulative_cost_usd

    api_key = require_env("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL",
                         "https://api.deepseek.com/anthropic")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    system_prompt = "你是一只小猫，从小猫的视角去回答问题"
    messages = [
        *conversation_history,
        {"role": "user", "content": message},
    ]
    client = Anthropic(api_key=api_key, base_url=base_url)

    with client.messages.stream(
        model=model,
        system=system_prompt,
        messages=messages,
        max_tokens=200,
    ) as stream:
        for event in stream:
            print(event, end="\n")
            print(event, end="", flush=True)
        final_message = stream.get_final_message()
        assistant_reply = extract_text(final_message)
        conversation_history.append({"role": "user", "content": message})
        conversation_history.append(
            {"role": "assistant", "content": assistant_reply}
        )
        round_cost_usd = calc_cost(
            model=model,
            input_tokens=getattr(final_message.usage, "input_tokens", None),
            output_tokens=getattr(final_message.usage, "output_tokens", None),
            cache_read_input_tokens=getattr(
                final_message.usage, "cache_read_input_tokens", None
            ),
        )
        cumulative_cost_usd += round_cost_usd
        print()
        print(
            "=== Usage ===\n"
            f"input_tokens={getattr(final_message.usage, 'input_tokens', None)}\n"
            f"output_tokens={getattr(final_message.usage, 'output_tokens', None)}\n"
            f"stop_reason={final_message.stop_reason}\n"
            f"round_cost_usd=${round_cost_usd:.8f}\n"
            f"cumulative_cost_usd=${cumulative_cost_usd:.8f}"
        )


def main() -> None:
    load_env()
    while True:
        user_message = input("请输入你的问题：")
        if user_message.strip().lower() in {"exit", "quit"}:
            break
        agentOutput(user_message)


if __name__ == "__main__":
    main()
