"""根据不同模型的用量与价格配置估算 Agent 运行费用。"""

from dataclasses import dataclass

from .config import AgentSettings
from .loop import RunStats


@dataclass(frozen=True)
class ModelPrices:
    """一个模型的输入、输出和缓存单价。"""

    input: float | None
    output: float | None
    cache_read: float | None
    cache_creation: float | None


def _main_prices(settings: AgentSettings) -> ModelPrices:
    return ModelPrices(
        settings.input_price_per_million,
        settings.output_price_per_million,
        settings.cache_read_price_per_million,
        settings.cache_creation_price_per_million,
    )


def _small_prices(settings: AgentSettings) -> ModelPrices:
    return ModelPrices(
        settings.small_input_price_per_million,
        settings.small_output_price_per_million,
        settings.small_cache_read_price_per_million,
        settings.small_cache_creation_price_per_million,
    )


def _router_prices(settings: AgentSettings) -> ModelPrices:
    return ModelPrices(
        settings.router_input_price_per_million,
        settings.router_output_price_per_million,
        settings.router_cache_read_price_per_million,
        settings.router_cache_creation_price_per_million,
    )


def _merge_prices(
    configured: ModelPrices,
    fallback: ModelPrices | None,
) -> ModelPrices:
    """允许角色价格只覆盖部分字段，其余字段沿用同模型价格。"""
    return ModelPrices(
        configured.input
        if configured.input is not None
        else fallback.input if fallback is not None else None,
        configured.output
        if configured.output is not None
        else fallback.output if fallback is not None else None,
        configured.cache_read
        if configured.cache_read is not None
        else fallback.cache_read if fallback is not None else None,
        configured.cache_creation
        if configured.cache_creation is not None
        else fallback.cache_creation if fallback is not None else None,
    )


def _agent_prices(
    settings: AgentSettings,
    model: str,
) -> ModelPrices:
    """按实际 Agent 模型选择主模型或 small 模型价格。"""
    main = _main_prices(settings)
    if settings.small_model is None or model != settings.small_model_name:
        # CLI 的 --model 是主模型覆盖，仍使用主模型价格配置。
        return main
    return _merge_prices(
        _small_prices(settings),
        (
            main
            if settings.small_model_name == settings.main_model_name
            else None
        ),
    )


def _router_model_prices(
    settings: AgentSettings,
    model: str,
) -> ModelPrices:
    """选择 Router 价格，并在同模型时复用已有模型价格。"""
    identity_prices: ModelPrices | None = None
    if model == settings.main_model_name:
        identity_prices = _main_prices(settings)
    elif (
        settings.small_model is not None
        and model == settings.small_model_name
    ):
        identity_prices = _agent_prices(settings, model)
    return _merge_prices(_router_prices(settings), identity_prices)


def _usage_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    prices: ModelPrices,
) -> float | None:
    """计算一组用量；只对实际出现的 token 要求对应单价。"""
    required_prices = (
        (input_tokens, prices.input),
        (output_tokens, prices.output),
        (cache_read_tokens, prices.cache_read),
        (cache_creation_tokens, prices.cache_creation),
    )
    if any(tokens > 0 and price is None for tokens, price in required_prices):
        return None
    return (
        input_tokens * (prices.input or 0)
        + output_tokens * (prices.output or 0)
        + cache_read_tokens * (prices.cache_read or 0)
        + cache_creation_tokens * (prices.cache_creation or 0)
    )


def estimate_router_cost(
    stats: RunStats,
    settings: AgentSettings,
) -> float | None:
    """估算 Router 自身费用；未发生 Router 调用时返回 0。"""
    stats = stats.aggregate()
    if stats.router_tokens == 0:
        return 0.0
    raw_cost = _usage_cost(
        input_tokens=stats.router_input_tokens,
        output_tokens=stats.router_output_tokens,
        cache_read_tokens=stats.router_cache_read_input_tokens,
        cache_creation_tokens=stats.router_cache_creation_input_tokens,
        prices=_router_model_prices(
            settings,
            stats.router_model or settings.router_model_name,
        ),
    )
    return None if raw_cost is None else raw_cost / 1_000_000


def estimate_cost(
    stats: RunStats,
    settings: AgentSettings,
) -> float | None:
    """估算 Router、Agent 和 compact 总费用。"""
    stats = stats.aggregate()
    selected_model = stats.selected_model or settings.main_model_name
    agent_prices = _agent_prices(settings, selected_model)
    agent_cost = _usage_cost(
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        cache_read_tokens=stats.cache_read_input_tokens,
        cache_creation_tokens=stats.cache_creation_input_tokens,
        prices=agent_prices,
    )

    compact_model = settings.compact_model or selected_model
    compact_fallback: ModelPrices | None = None
    if compact_model == selected_model:
        compact_fallback = agent_prices
    elif compact_model in {settings.main_model_name, settings.model}:
        compact_fallback = _main_prices(settings)
    elif (
        settings.small_model is not None
        and compact_model == settings.small_model_name
    ):
        compact_fallback = _agent_prices(settings, compact_model)
    compact_prices = _merge_prices(
        ModelPrices(
            settings.compact_input_price_per_million,
            settings.compact_output_price_per_million,
            settings.compact_cache_read_price_per_million,
            settings.compact_cache_creation_price_per_million,
        ),
        compact_fallback,
    )
    compact_cost = _usage_cost(
        input_tokens=stats.compact_input_tokens,
        output_tokens=stats.compact_output_tokens,
        cache_read_tokens=stats.compact_cache_read_input_tokens,
        cache_creation_tokens=stats.compact_cache_creation_input_tokens,
        prices=compact_prices,
    )
    router_cost = estimate_router_cost(stats, settings)

    if agent_cost is None or compact_cost is None or router_cost is None:
        return None
    return (agent_cost + compact_cost) / 1_000_000 + router_cost
