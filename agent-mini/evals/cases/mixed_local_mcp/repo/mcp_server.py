from mcp.server.mcpserver import MCPServer


mcp = MCPServer("incident-policy")


@mcp.tool()
def lookup_policy(topic: str) -> str:
    """Return the notification policy for an incident topic."""
    if topic.strip().lower() == "critical":
        return "Critical incidents must notify both pager and email."
    return "Only the default channel is required."


if __name__ == "__main__":
    mcp.run()
