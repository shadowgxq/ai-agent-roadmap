def display_name(
    first_name: str,
    last_name: str,
    nickname: str = "",
) -> str:
    if nickname:
        return nickname
    return f"{first_name} {last_name}"

