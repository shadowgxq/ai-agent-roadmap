"""加载 agent-mini 的模型与运行配置。"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

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
        populate_by_name=True,
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
    main_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAIN_MODEL", "CODEX_MAIN_MODEL"),
    )
    small_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMALL_MODEL"),
    )
    enable_router: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "ROUTER_ENABLED",
            "ENABLE_ROUTER",
            "router_enabled",
        ),
    )
    judge_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("JUDGE_MODEL"),
    )
    pricing_file: Path = Field(
        default=PROJECT_ROOT / "config" / "model_prices.yaml",
        validation_alias=AliasChoices("PRICING_FILE"),
    )
    log_file: Path = PROJECT_ROOT / "logs" / "agent.jsonl"
    max_turns: int = 30
    max_tool_output_chars: int = 10_000
    executor_backend: Literal["local", "docker"] = Field(
        default="local",
        validation_alias=AliasChoices(
            "EXECUTOR_BACKEND",
            "AGENT_EXECUTOR_BACKEND",
        ),
    )
    docker_image: str = Field(
        default="agent-mini-sandbox:local",
        validation_alias=AliasChoices("DOCKER_IMAGE", "AGENT_DOCKER_IMAGE"),
    )
    docker_binary: str = Field(
        default="docker",
        validation_alias=AliasChoices("DOCKER_BINARY", "AGENT_DOCKER_BINARY"),
    )
    docker_timeout: float = Field(
        default=30.0,
        gt=0,
        validation_alias=AliasChoices("DOCKER_TIMEOUT", "AGENT_DOCKER_TIMEOUT"),
    )
    docker_cpu_limit: float = Field(
        default=1.0,
        gt=0,
        validation_alias=AliasChoices(
            "DOCKER_CPU_LIMIT",
            "AGENT_DOCKER_CPU_LIMIT",
        ),
    )
    docker_memory_limit: str = Field(
        default="512m",
        min_length=1,
        validation_alias=AliasChoices(
            "DOCKER_MEMORY_LIMIT",
            "AGENT_DOCKER_MEMORY_LIMIT",
        ),
    )
    docker_pids_limit: int = Field(
        default=128,
        gt=0,
        validation_alias=AliasChoices(
            "DOCKER_PIDS_LIMIT",
            "AGENT_DOCKER_PIDS_LIMIT",
        ),
    )
    docker_container_user: str = Field(
        default="10001:10001",
        min_length=1,
        validation_alias=AliasChoices(
            "DOCKER_CONTAINER_USER",
            "AGENT_DOCKER_CONTAINER_USER",
        ),
    )
    context_window_tokens: int = Field(
        default=128_000,
        ge=1,
        validation_alias=AliasChoices(
            "CONTEXT_WINDOW_TOKENS",
            "CONTEXT_WINDOW",
        ),
    )
    prompt_cache_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "PROMPT_CACHE_ENABLED",
            "ENABLE_PROMPT_CACHE",
            "ENABLE_CACHE",
        ),
    )
    prompt_cache_key: str = Field(default="agent-mini", min_length=1)
    prompt_cache_retention: str | None = None
    compact_enabled: bool = True
    compact_threshold: float = Field(default=0.7, gt=0, lt=1)
    compact_keep_recent: int = Field(default=4, ge=1)
    compact_model: str | None = None
    compact_max_tokens: int = Field(default=1000, ge=1)
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
    def main_model_name(self) -> str:
        """返回任务主模型；兼容已有的 model 配置。"""
        return self.main_model or self.model

    @property
    def router_enabled(self) -> bool:
        """兼容代码中使用的 Router 开关命名。"""
        return self.enable_router

    @property
    def small_model_name(self) -> str:
        """返回 simple 任务使用的模型，缺省回退到主模型。"""
        return self.small_model or self.main_model_name

    @property
    def router_model_name(self) -> str:
        """Router 与 simple 任务共用 small 模型，不再单独配置。"""
        return self.small_model_name

    @property
    def resolved_mcp_config_file(self) -> Path:
        """把相对 MCP 配置路径固定到 agent-mini 项目目录。"""
        if self.mcp_config_file.is_absolute():
            return self.mcp_config_file
        return PROJECT_ROOT / self.mcp_config_file

    @property
    def resolved_pricing_file(self) -> Path:
        """把相对价格表路径固定到 agent-mini 项目目录。"""
        if self.pricing_file.is_absolute():
            return self.pricing_file
        return PROJECT_ROOT / self.pricing_file

    @property
    def langfuse_configured(self) -> bool:
        """Langfuse 已启用且必要凭证完整。"""
        return (
            self.langfuse_enabled
            and bool(self.langfuse_public_key)
            and bool(self.langfuse_secret_key)
        )
