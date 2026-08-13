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
_RESOURCE_TEMPLATE_VARIABLE = re.compile(r"\{[^{}]+\}")


class MCPServerConfig(BaseModel):
    """一个本地 stdio MCP server 的启动配置。"""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    enabled: bool = True
    resources: list[str] = Field(default_factory=list)
    resource_max_chars: int = Field(default=4000, ge=1, le=20_000)


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


def _resource_template_matches(template: str, uri: str) -> bool:
    """匹配 MCP 的简单 URI 模板变量，例如 lesson://{topic}。"""
    parts = _RESOURCE_TEMPLATE_VARIABLE.split(template)
    pattern_parts: list[str] = []
    for index, part in enumerate(parts):
        pattern_parts.append(re.escape(part))
        if index < len(parts) - 1:
            pattern_parts.append("[^/?#]+")
    return re.fullmatch("".join(pattern_parts), uri) is not None


def _truncate_resource_text(value: str, max_chars: int) -> str:
    """限制资源进入上下文的长度，保留尾部省略标记。"""
    normalized = value.strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1]}…"


def _serialize_resource_result(
    result: types.ReadResourceResult,
    *,
    server_name: str,
    requested_uri: str,
    max_chars: int,
) -> str:
    """把 MCP resource 转成带来源标记的安全文本上下文。"""
    blocks: list[str] = []
    remaining_chars = max_chars
    for content in result.contents:
        content_uri = getattr(content, "uri", requested_uri)
        if isinstance(content, types.TextResourceContents):
            if remaining_chars <= 0:
                break
            text = _truncate_resource_text(content.text, remaining_chars)
            blocks.append(
                f"[MCP resource server={server_name} uri={content_uri}]\n"
                f"{text}"
            )
            remaining_chars -= len(text)
            continue

        # 二进制内容不能直接作为 prompt 注入，避免把 base64 数据扩大上下文。
        mime_type = getattr(content, "mime_type", None) or "unknown"
        blocks.append(
            f"[MCP resource server={server_name} uri={content_uri}]\n"
            f"(binary resource omitted; mime_type={mime_type})"
        )

    if not blocks:
        return (
            f"[MCP resource server={server_name} uri={requested_uri}]\n"
            "(resource returned no readable content)"
        )
    return "\n\n".join(blocks)


class MCPClientManager:
    """维护 MCP 子进程、session 以及动态工具注册的生命周期。"""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path.resolve()
        self._stack = AsyncExitStack()
        self._resource_blocks: list[str] = []

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
        await self._load_configured_resources(
            server_name,
            session,
            config,
        )
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

    @property
    def resource_context(self) -> str:
        """返回已按配置读取的 MCP resource 上下文。"""
        return "\n\n".join(self._resource_blocks)

    async def _load_configured_resources(
        self,
        server_name: str,
        session: ClientSession,
        config: MCPServerConfig,
    ) -> None:
        """发现并读取一个 server 配置白名单中的 resource。"""
        if not config.resources:
            return

        resources = await self._list_all_resources(session)
        templates = await self._list_all_resource_templates(session)
        known_uris = {resource.uri for resource in resources}
        known_templates = [template.uri_template for template in templates]

        for uri in config.resources:
            if uri not in known_uris and not any(
                _resource_template_matches(template, uri)
                for template in known_templates
            ):
                available = sorted(known_uris | set(known_templates))
                available_text = ", ".join(available) or "无"
                raise ValueError(
                    f"MCP server {server_name} 未暴露 resource URI“{uri}”；"
                    f"可用资源：{available_text}"
                )

            try:
                result = await session.read_resource(uri)
            except Exception as exc:
                raise RuntimeError(
                    f"读取 MCP resource 失败：server={server_name}, uri={uri}: {exc}"
                ) from exc

            self._resource_blocks.append(
                _serialize_resource_result(
                    result,
                    server_name=server_name,
                    requested_uri=uri,
                    max_chars=config.resource_max_chars,
                )
            )

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

    async def _list_all_resources(
        self,
        session: ClientSession,
    ) -> list[types.Resource]:
        """跟随 cursor 拉取 server 暴露的固定 resource。"""
        resources: list[types.Resource] = []
        cursor: str | None = None
        while True:
            params = (
                types.PaginatedRequestParams(cursor=cursor)
                if cursor is not None
                else None
            )
            result = await session.list_resources(params=params)
            resources.extend(result.resources)
            cursor = result.next_cursor
            if cursor is None:
                return resources

    async def _list_all_resource_templates(
        self,
        session: ClientSession,
    ) -> list[types.ResourceTemplate]:
        """跟随 cursor 拉取 server 暴露的 resource template。"""
        templates: list[types.ResourceTemplate] = []
        cursor: str | None = None
        while True:
            params = (
                types.PaginatedRequestParams(cursor=cursor)
                if cursor is not None
                else None
            )
            result = await session.list_resource_templates(params=params)
            templates.extend(result.resource_templates)
            cursor = result.next_cursor
            if cursor is None:
                return templates

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
