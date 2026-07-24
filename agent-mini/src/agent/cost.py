"""根据模型用量与价格配置估算 Agent 运行费用。"""

from .config import AgentSettings
from .loop import RunStats


def estimate_cost(
    stats: RunStats,
    settings: AgentSettings,
) -> float | None:
    """估算运行费用；缺少实际用到的 token 单价时返回 None。"""
    if (
        settings.input_price_per_million is None
        or settings.output_price_per_million is None
    ):
        return None

    if (
        stats.cache_read_input_tokens > 0
        and settings.cache_read_price_per_million is None
    ):
        return None

    if (
        stats.cache_creation_input_tokens > 0
        and settings.cache_creation_price_per_million is None
    ):
        return None

    return (
        stats.input_tokens * settings.input_price_per_million
        + stats.output_tokens * settings.output_price_per_million
        + stats.cache_read_input_tokens
        * (settings.cache_read_price_per_million or 0)
        + stats.cache_creation_input_tokens
        * (settings.cache_creation_price_per_million or 0)
    ) / 1_000_000
