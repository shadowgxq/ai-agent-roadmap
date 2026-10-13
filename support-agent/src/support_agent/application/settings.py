"""Application settings can load without constructing a model client."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from support_agent.config.settings import PROJECT_ROOT


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUPPORT_APP_", env_file=PROJECT_ROOT / ".env", extra="ignore")
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    session_secret: SecretStr = Field(min_length=32)
    # Provisioned accounts: username -> {password_hash, organization_id, user_id, role}.
    accounts: dict[str, dict[str, str]] = Field(default_factory=dict)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    secure_cookie: bool = True
    session_seconds: int = Field(default=3600, ge=60, le=86400)
    lease_seconds: int = Field(default=120, ge=30)
    max_attempts: int = Field(default=3, ge=1, le=10)
    tracing_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    input_price_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_price_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
