"""跨 week 复用的最基础工具：环境加载、配置、SDK 客户端获取、响应解析。

所有 week 代码共用 `code/` 根目录的 uv 环境，通过 `agent_sdk` 复用：

    from agent_sdk import load_config, get_client, extract_text
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anthropic import Anthropic, AsyncAnthropic
from dotenv import load_dotenv


# shared -> code -> 仓库根目录
ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT / ".env"

DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_MODEL = "deepseek-chat"


def load_env() -> None:
    """从仓库根目录加载 .env。"""
    load_dotenv(ENV_PATH)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


@dataclass(frozen=True)
class Config:
    """一次请求所需的最小配置。"""

    api_key: str
    base_url: str
    model: str


def load_config() -> Config:
    """加载 .env 并读取 api_key / base_url / model。"""
    load_env()
    return Config(
        api_key=require_env("ANTHROPIC_API_KEY"),
        base_url=os.getenv("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL),
        model=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
    )


def get_client(config: Config | None = None) -> Anthropic:
    """获取同步 SDK 客户端；不传 config 时自动 load_config()。"""
    config = config or load_config()
    return Anthropic(api_key=config.api_key, base_url=config.base_url)


def get_async_client(config: Config | None = None) -> AsyncAnthropic:
    """获取异步 SDK 客户端；不传 config 时自动 load_config()。"""
    config = config or load_config()
    return AsyncAnthropic(api_key=config.api_key, base_url=config.base_url)


def extract_text(message: Any) -> str:
    """把响应里的所有 text block 拼成一段正文。"""
    parts: list[str] = []
    for block in getattr(message, "content", []):
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


def extract_assistant_blocks(message: Any) -> list[dict[str, Any]]:
    """把响应还原成可回填到 messages 的 assistant content（含 tool_use）。"""
    blocks: list[dict[str, Any]] = []
    for block in message.content:
        if block.type == "text":
            blocks.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return blocks


def fmt_usage(usage: object | None) -> str:
    """把 usage 统计格式化成一行，缺省字段显示 None。"""
    if usage is None:
        return "-"
    return (
        f"input={getattr(usage, 'input_tokens', None)}, "
        f"output={getattr(usage, 'output_tokens', None)}, "
        f"cache_create={getattr(usage, 'cache_creation_input_tokens', None)}, "
        f"cache_read={getattr(usage, 'cache_read_input_tokens', None)}"
    )
