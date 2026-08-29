"""Runtime configuration for the support-agent project."""

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class AgentSettings(BaseSettings):
    """Load model and run-level limits outside graph or service logic."""

    model_config = SettingsConfigDict(
        env_prefix="SUPPORT_AGENT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model: str = Field(min_length=1)
    api_key: SecretStr = Field(min_length=1)
    base_url: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_run_cost_usd: Decimal = Field(default=Decimal("0.50"), gt=0)
    deepseek_thinking_mode: Literal["enabled", "disabled"] = "disabled"
    database_url: str = Field(min_length=1)

    @property
    def resolved_base_url(self) -> str | None:
        """Treat an empty optional gateway URL as the provider default."""

        if self.base_url is None:
            return None
        value = self.base_url.strip()
        return value or None
