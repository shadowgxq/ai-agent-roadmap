"""Tool registry and built-in tools."""

from .fs import register_fs_tools, resolve_path
from .registry import (
    RegisteredTool,
    ToolExecutionResult,
    ToolRegistry,
    registry,
    tool,
)
from .search import register_search_tools
from .shell import register_shell_tools
from .tools import get_weather


__all__ = [
    "RegisteredTool",
    "ToolExecutionResult",
    "ToolRegistry",
    "get_weather",
    "registry",
    "tool",
    "register_fs_tools",
    "resolve_path",
    "register_search_tools",
    "register_shell_tools",
]
