class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def register(self, name: str, tool: object) -> None:
        self.tools[name] = tool

    def execute(self, name: str, arguments: dict[str, object]) -> str:
        tool = self.tools[name]
        return tool.execute(arguments)  # type: ignore[attr-defined]
