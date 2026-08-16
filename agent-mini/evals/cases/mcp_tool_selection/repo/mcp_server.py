from mcp.server.mcpserver import MCPServer


mcp = MCPServer("policy")


@mcp.tool()
def lookup_policy(topic: str) -> str:
    """Look up a business policy before changing local code."""
    if topic.strip().lower() == "shipping":
        return (
            "Free shipping is calculated from the discounted subtotal. "
            "A discounted subtotal below 100.00 pays the standard fee."
        )
    return "No policy is registered for this topic."


if __name__ == "__main__":
    mcp.run()
