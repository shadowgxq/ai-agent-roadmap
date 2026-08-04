"""根据模型用量与价格配置估算 Agent 运行费用。"""

from .config import AgentSettings
from .loop import RunStats


def _compact_price(
    configured_price: float | None,
    main_price: float | None,
    *,
    uses_main_model: bool,
) -> float | None:
    """同模型沿用主价格，不同模型必须提供独立价格。"""
    if configured_price is not None:
        return configured_price
    return main_price if uses_main_model else None


def estimate_cost(
    stats: RunStats,
    settings: AgentSettings,
) -> float | None:
    """估算运行费用；缺少实际用到的 token 单价时返回 None。"""
    stats = stats.aggregate()
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

    main_cost = (
        stats.input_tokens * settings.input_price_per_million
        + stats.output_tokens * settings.output_price_per_million
        + stats.cache_read_input_tokens
        * (settings.cache_read_price_per_million or 0)
        + stats.cache_creation_input_tokens
        * (settings.cache_creation_price_per_million or 0)
    )

    uses_main_model = (
        not settings.compact_model
        or settings.compact_model == settings.model
    )
    compact_input_price = _compact_price(
        settings.compact_input_price_per_million,
        settings.input_price_per_million,
        uses_main_model=uses_main_model,
    )
    compact_output_price = _compact_price(
        settings.compact_output_price_per_million,
        settings.output_price_per_million,
        uses_main_model=uses_main_model,
    )
    compact_cache_read_price = _compact_price(
        settings.compact_cache_read_price_per_million,
        settings.cache_read_price_per_million,
        uses_main_model=uses_main_model,
    )
    compact_cache_creation_price = _compact_price(
        settings.compact_cache_creation_price_per_million,
        settings.cache_creation_price_per_million,
        uses_main_model=uses_main_model,
    )

    required_compact_prices = (
        (stats.compact_input_tokens, compact_input_price),
        (stats.compact_output_tokens, compact_output_price),
        (stats.compact_cache_read_input_tokens, compact_cache_read_price),
        (
            stats.compact_cache_creation_input_tokens,
            compact_cache_creation_price,
        ),
    )
    if any(
        tokens > 0 and price is None
        for tokens, price in required_compact_prices
    ):
        return None

    compact_cost = (
        stats.compact_input_tokens * (compact_input_price or 0)
        + stats.compact_output_tokens * (compact_output_price or 0)
        + stats.compact_cache_read_input_tokens
        * (compact_cache_read_price or 0)
        + stats.compact_cache_creation_input_tokens
        * (compact_cache_creation_price or 0)
    )
    return (main_cost + compact_cost) / 1_000_000
