"""加载 agent-mini 的模型与运行配置。"""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AgentSettings(BaseSettings):
    """从环境变量或 .env 文件读取 Agent 配置。"""

    model_config = SettingsConfigDict(
        # 父目录配置先加载，项目自己的 .env 可以覆盖它。
        env_file=(PROJECT_ROOT.parent / ".env", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY")
    )
    base_url: str = Field(
        default="https://api.deepseek.com/anthropic",
        validation_alias=AliasChoices("ANTHROPIC_BASE_URL", "DEEPSEEK_BASE_URL"),
    )
    model: str = Field(default="deepseek-chat", validation_alias="DEEPSEEK_MODEL")
    max_turns: int = 30
    max_tool_output_chars: int = 10_000
