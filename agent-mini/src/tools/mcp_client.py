"""把 stdio MCP server 暴露的工具接入 agent-mini 注册表。"""

from __future__ import annotations

import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from types import TracebackType
from typing import Any

from mcp import types
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import BaseModel, ConfigDict, Field

from .registry import ToolExecutionResult, ToolRegistry


_SERVER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class MCPServerConfig(BaseModel):
    """一个本地 stdio MCP server 的启动配置。"""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    enabled: bool = True


class MCPServersConfig(BaseModel):
    """agent-mini 可连接的 MCP server 集合。"""

    model_config = ConfigDict(extra="forbid")

    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


def load_mcp_servers(path: Path) -> MCPServersConfig:
    """读取并校验 MCP server 配置。"""
    if not path.is_file():
        raise FileNotFoundError(f"MCP 配置文件不存在: {path}")
    config = MCPServersConfig.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    invalid_names = [
        name
        for name in config.servers
        if not _SERVER_NAME_PATTERN.fullmatch(name)
    ]
    if invalid_names:
        raise ValueError(
            "MCP server 名称只能包含字母、数字、下划线和连字符: "
            + ", ".join(sorted(invalid_names))
        )
    return config


def _serialize_call_result(result: types.CallToolResult) -> str:
    """把 MCP 内容块转换成适合回填 Agent 上下文的文本。"""
    text_blocks = [
        block.text
        for block in result.content
        if isinstance(block, types.TextContent)
    ]
    if (
        len(text_blocks) == len(result.content)
        and result.structured_content is None
    ):
        return "\n".join(text_blocks)

    payload: dict[str, Any] = {
        "content": [
            block.model_dump(mode="json", by_alias=True, exclude_none=True)
            for block in result.content
        ]
    }
    if result.structured_content is not None:
        payload["structured_content"] = result.structured_content
    return json.dumps(payload, ensure_ascii=False, default=str)


class MCPClientManager:
    """维护 MCP 子进程、session 以及动态工具注册的生命周期。"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path.resolve()
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> MCPClientManager:
        await self._stack.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return await self._stack.__aexit__(
            exc_type,
            exc_value,
            traceback,
        )

    async def connect_all(self, registry: ToolRegistry) -> int:
        """连接所有启用的 server，并把远程工具注册到本地注册表。"""
        config = load_mcp_servers(self.config_path)
        registered_count = 0
        for server_name, server_config in config.servers.items():
            if not server_config.enabled:
                continue
            registered_count += await self._connect_server(
                server_name,
                server_config,
                registry,
            )
        return registered_count

    async def _connect_server(
        self,
        server_name: str,
        config: MCPServerConfig,
        registry: ToolRegistry,
    ) -> int:
        cwd = self._resolve_cwd(config.cwd)
        streams = await self._stack.enter_async_context(
            stdio_client(
                StdioServerParameters(
                    command=config.command,
                    args=config.args,
                    env=config.env,
                    cwd=cwd,
                )
            )
        )
        read_stream, write_stream = streams
        session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        remote_tools = await self._list_all_tools(session)

        for remote_tool in remote_tools:
            qualified_name = f"{server_name}__{remote_tool.name}"

            async def call_remote_tool(
                input_data: dict[str, Any],
                *,
                current_session: ClientSession = session,
                remote_name: str = remote_tool.name,
            ) -> ToolExecutionResult:
                result = await current_session.call_tool(
                    remote_name,
                    arguments=input_data,
                )
                return ToolExecutionResult(
                    content=_serialize_call_result(result),
                    is_error=result.is_error,
                )

            registry.register_json_tool(
                call_remote_tool,
                name=qualified_name,
                description=(
                    remote_tool.description
                    or f"MCP tool {remote_tool.name} from {server_name}."
                ),
                input_schema=remote_tool.input_schema,
            )

        return len(remote_tools)

    async def _list_all_tools(
        self,
        session: ClientSession,
    ) -> list[types.Tool]:
        """跟随 cursor 拉取 server 暴露的完整工具列表。"""
        tools: list[types.Tool] = []
        cursor: str | None = None
        while True:
            params = (
                types.PaginatedRequestParams(cursor=cursor)
                if cursor is not None
                else None
            )
            result = await session.list_tools(params=params)
            tools.extend(result.tools)
            cursor = result.next_cursor
            if cursor is None:
                return tools

    def _resolve_cwd(self, configured_cwd: str | None) -> Path | None:
        if configured_cwd is None:
            return None
        cwd = Path(configured_cwd)
        if not cwd.is_absolute():
            cwd = self.config_path.parent / cwd
        return cwd.resolve()


__all__ = [
    "MCPClientManager",
    "MCPServerConfig",
    "MCPServersConfig",
    "load_mcp_servers",
]
