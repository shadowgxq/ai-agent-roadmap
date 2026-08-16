from src.context import Context
from src.tools import ToolRegistry


def run_agent(context: Context, registry: ToolRegistry) -> str:
    """The real project would call the model and iterate until a final answer."""
    return f"tools={len(registry.tools)}, messages={len(context.messages)}"
