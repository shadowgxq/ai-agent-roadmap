class Context:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def append(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
