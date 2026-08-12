"""Minimal MCP server for the W08 learning exercises."""

from mcp.server.mcpserver import MCPServer


mcp = MCPServer("learning-playground")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""

    return a + b


@mcp.resource("lesson://{topic}")
def lesson(topic: str) -> str:
    """Return a short local lesson resource for a topic."""

    topic = topic.strip() or "MCP"
    return (
        f"主题：{topic}\n"
        "这是由 learning-playground 提供的本地 MCP resource。"
    )


@mcp.prompt()
def explain(topic: str, level: str = "beginner") -> str:
    """Build a reusable explanation prompt for a topic."""

    return (
        f"请用 {level} 难度解释主题“{topic}”，"
        "并给出一个简短的 Python 示例。"
    )


if __name__ == "__main__":
    # No transport argument means stdio: a host launches this process and
    # exchanges MCP messages through stdin/stdout.
    mcp.run()
