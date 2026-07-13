from agent_sdk import extract_text, get_client, load_config


def main() -> None:
    config = load_config()
    model = config.model
    system_prompt = "你是一个简洁、准确的中文助理。"
    user_message = "今天天气怎么样"
    max_tokens = 200
    client = get_client(config)

    messages = [
        {"role": "user", "content": user_message},
    ]
    response = client.messages.create(
        model=model,
        system=system_prompt,
        messages=messages,
        max_tokens=max_tokens,
    )

    reply = extract_text(response)
    print("==reply", reply)


if __name__ == "__main__":
    main()
