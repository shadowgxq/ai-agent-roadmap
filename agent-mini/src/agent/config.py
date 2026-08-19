"""加载 agent-mini 的模型与运行配置。"""

from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .cache import PromptCacheConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]

ConfirmCallback = Callable[[str, str], bool | Awaitable[bool]]


class AgentSettings(BaseSettings):
    """从环境变量或 .env 文件读取 Agent 配置。"""

    model_config = SettingsConfigDict(
        # 父目录配置先加载，项目自己的 .env 可以覆盖它。
        env_file=(PROJECT_ROOT.parent / ".env", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(
        validation_alias=AliasChoices(
            "CODEX_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
        )
    )
    base_url: str = Field(
        default="http://165.154.255.250:8080/v1",
        validation_alias=AliasChoices(
            "CODEX_BASE_URL",
            "OPENAI_BASE_URL",
            "ANTHROPIC_BASE_URL",
            "DEEPSEEK_BASE_URL",
        ),
    )
    model: str = Field(
        default="gpt-5.6-luna",
        validation_alias=AliasChoices(
            "CODEX_MODEL",
            "OPENAI_MODEL",
            "DEEPSEEK_MODEL",
        ),
    )
    judge_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("JUDGE_MODEL"),
    )
    log_file: Path = PROJECT_ROOT / "logs" / "agent.jsonl"
    max_turns: int = 30
    max_tool_output_chars: int = 10_000
    context_window_tokens: int = Field(
        default=128_000,
        ge=1,
        validation_alias=AliasChoices(
            "CONTEXT_WINDOW_TOKENS",
            "CONTEXT_WINDOW",
        ),
    )
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    cache_read_price_per_million: float | None = Field(default=None, ge=0)
    cache_creation_price_per_million: float | None = Field(
        default=None,
        ge=0,
    )
    prompt_cache_enabled: bool = True
    prompt_cache_key: str = Field(default="agent-mini", min_length=1)
    prompt_cache_retention: str | None = None
    price_currency: str = "USD"
    compact_enabled: bool = True
    compact_threshold: float = Field(default=0.7, gt=0, lt=1)
    compact_keep_recent: int = Field(default=4, ge=1)
    compact_model: str | None = None
    compact_max_tokens: int = Field(default=1000, ge=1)
    compact_input_price_per_million: float | None = Field(
        default=None,
        ge=0,
    )
    compact_output_price_per_million: float | None = Field(
        default=None,
        ge=0,
    )
    compact_cache_read_price_per_million: float | None = Field(
        default=None,
        ge=0,
    )
    compact_cache_creation_price_per_million: float | None = Field(
        default=None,
        ge=0,
    )
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str = Field(
        default="text-embedding-3-small",
        min_length=1,
    )
    embedding_batch_size: int = Field(default=64, ge=1)
    mcp_enabled: bool = False
    mcp_config_file: Path = PROJECT_ROOT / "mcp_servers.json"

    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"

    @field_validator("base_url")
    @classmethod
    def ensure_openai_v1(cls, value: str) -> str:
        """把网关根地址规范成 OpenAI SDK 需要的 `/v1` 地址。"""
        value = value.rstrip("/")
        return value if value.endswith("/v1") else f"{value}/v1"

    @field_validator("embedding_base_url")
    @classmethod
    def ensure_embedding_v1(cls, value: str | None) -> str | None:
        """规范可选的独立 embedding 服务地址。"""
        if value is None:
            return None
        value = value.rstrip("/")
        return value if value.endswith("/v1") else f"{value}/v1"

    @property
    def prompt_cache_config(self) -> PromptCacheConfig:
        """Build the cache options shared by all model call paths."""
        return PromptCacheConfig(
            enabled=self.prompt_cache_enabled,
            key=self.prompt_cache_key,
            retention=self.prompt_cache_retention,
        )

    @property
    def resolved_mcp_config_file(self) -> Path:
        """把相对 MCP 配置路径固定到 agent-mini 项目目录。"""
        if self.mcp_config_file.is_absolute():
            return self.mcp_config_file
        return PROJECT_ROOT / self.mcp_config_file

    @property
    def langfuse_configured(self) -> bool:
        """Langfuse 已启用且必要凭证完整。"""
        return (
            self.langfuse_enabled
            and bool(self.langfuse_public_key)
            and bool(self.langfuse_secret_key)
        )
