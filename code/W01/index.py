from pricing import calc_cost
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "shared"))

from agent_sdk import extract_text, get_client, load_config  # noqa: E402


conversation_history: list[dict[str, str]] = []
cumulative_cost_usd = 0.0


def agentOutput(message: str) -> None:
    global cumulative_cost_usd

    config = load_config()
    model = config.model
    system_prompt = "你是一只小猫，从小猫的视角去回答问题"
    messages = [
        *conversation_history,
        {"role": "user", "content": message},
    ]
    client = get_client(config)

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
    while True:
        user_message = input("请输入你的问题：")
        if user_message.strip().lower() in {"exit", "quit"}:
            break
        agentOutput(user_message)


if __name__ == "__main__":
    main()
