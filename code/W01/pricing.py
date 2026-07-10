from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_cache_miss_per_million: float
    input_cache_hit_per_million: float
    output_per_million: float


# Prices are in USD per 1M tokens.
# Source used for this learning step: DeepSeek official pricing page.
MODEL_PRICES: dict[str, ModelPrice] = {
    "deepseek-v4-flash": ModelPrice(
        input_cache_miss_per_million=0.14,
        input_cache_hit_per_million=0.0028,
        output_per_million=0.28,
    ),
    "deepseek-v4-pro": ModelPrice(
        input_cache_miss_per_million=0.435,
        input_cache_hit_per_million=0.003625,
        output_per_million=0.87,
    ),
    # DeepSeek docs state these aliases map to deepseek-v4-flash and will be
    # deprecated on 2026-07-24 15:59 UTC.
    "deepseek-chat": ModelPrice(
        input_cache_miss_per_million=0.14,
        input_cache_hit_per_million=0.0028,
        output_per_million=0.28,
    ),
    "deepseek-reasoner": ModelPrice(
        input_cache_miss_per_million=0.14,
        input_cache_hit_per_million=0.0028,
        output_per_million=0.28,
    ),
}


def calc_cost(
    *,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cache_read_input_tokens: int | None = None,
) -> float:
    price = MODEL_PRICES.get(model)
    if price is None:
        return 0.0

    uncached_input_tokens = input_tokens or 0
    cached_input_tokens = cache_read_input_tokens or 0
    total_output_tokens = output_tokens or 0

    input_cost = uncached_input_tokens / 1_000_000 * \
        price.input_cache_miss_per_million
    input_cost += cached_input_tokens / 1_000_000 * price.input_cache_hit_per_million
    output_cost = total_output_tokens / 1_000_000 * price.output_per_million
    return input_cost + output_cost
