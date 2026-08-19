"""统一管理模型价格、Token 成本计算和成本输出。"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .config import AgentSettings

if TYPE_CHECKING:
    from .loop import RunStats, UsageTokens


USAGE_PRICE_FIELDS = (
    ("input_tokens", "input_per_million"),
    ("output_tokens", "output_per_million"),
    ("cache_read_input_tokens", "cache_read_per_million"),
    ("cache_creation_input_tokens", "cache_creation_per_million"),
)
USAGE_FIELDS = tuple(token_field for token_field, _ in USAGE_PRICE_FIELDS)
PRICE_FIELDS = tuple(price_field for _, price_field in USAGE_PRICE_FIELDS)
COST_FIELDS = ("agent_usd", "compact_usd", "router_usd", "judge_usd")


class _UniqueKeyLoader(yaml.SafeLoader):
    """拒绝 YAML 中静默覆盖的重复 key。"""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.Node,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise ValueError(f"价格表包含重复字段: {key}")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _as_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("价格必须是非负数字或 null")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("价格必须是非负有限数字")
    return value


class ModelPrice(BaseModel):
    """单个实际模型名对应的百万 Token 价格。"""

    model_config = ConfigDict(extra="forbid")

    input_per_million: float | None
    output_per_million: float | None
    cache_read_per_million: float | None
    cache_creation_per_million: float | None

    @field_validator(*PRICE_FIELDS, mode="before")
    @classmethod
    def validate_price(cls, value: Any) -> float | None:
        return _as_price(value)


def _reject_unknown(
    payload: dict[Any, Any],
    expected: set[str],
    message: str,
) -> None:
    if unknown := set(payload) - expected:
        raise ValueError(f"{message}: {sorted(unknown)}")


class PriceTable(BaseModel):
    """可版本管理的模型价格映射。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    currency: str
    models: dict[str, ModelPrice]

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value.strip().upper() != "USD":
            raise ValueError("价格映射文件 currency 当前必须为 USD")
        return "USD"

    @field_validator("models")
    @classmethod
    def validate_models(
        cls, value: dict[str, ModelPrice]
    ) -> dict[str, ModelPrice]:
        if not value:
            raise ValueError("价格映射文件 models 必须是非空对象")
        if any(not model.strip() for model in value):
            raise ValueError("价格映射中的模型名必须是非空字符串")
        return value

    @classmethod
    def load(cls, path: Path | str) -> "PriceTable":
        """从 YAML 加载并严格校验价格表。"""
        resolved_path = Path(path).expanduser()
        try:
            with resolved_path.open(encoding="utf-8") as file:
                payload = yaml.load(file, Loader=_UniqueKeyLoader)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"价格映射文件不存在: {resolved_path}"
            ) from None
        except yaml.YAMLError as exc:
            raise ValueError(
                f"价格映射文件 YAML 无效: {resolved_path}: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError("价格映射文件根节点必须是对象")
        _reject_unknown(
            payload,
            {"version", "currency", "models"},
            "价格映射文件包含未知字段",
        )
        raw_models = payload.get("models")
        if isinstance(raw_models, dict):
            for model, raw_price in raw_models.items():
                if isinstance(raw_price, dict):
                    _reject_unknown(
                        raw_price,
                        set(PRICE_FIELDS),
                        f"模型 {model} 包含未知价格字段",
                    )
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"价格映射文件无效: {resolved_path}: {exc}") from exc

    def price_for(self, model: str) -> ModelPrice | None:
        """按实际模型名查找价格，不做角色或主模型回退。"""
        return self.models.get(model)


@dataclass(frozen=True)
class CostBreakdown:
    """一次任务的分层成本明细。"""

    currency: str = "USD"
    agent_usd: float | None = 0.0
    compact_usd: float | None = 0.0
    router_usd: float | None = 0.0
    judge_usd: float | None = 0.0
    task_usd: float | None = 0.0
    total_usd: float | None = 0.0
    available: bool = True
    missing_prices: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """返回 JSON 日志、Langfuse 和 Eval 共用的结构。"""
        data = asdict(self)
        data["missing_prices"] = list(self.missing_prices)
        return data

    @classmethod
    def unavailable(
        cls,
        *,
        currency: str = "USD",
        reason: str = "cost_unavailable",
    ) -> "CostBreakdown":
        """构造统一的不可用成本，避免调用方重复填充 None 字段。"""
        return cls(
            currency=currency,
            agent_usd=None,
            compact_usd=None,
            router_usd=None,
            judge_usd=None,
            task_usd=None,
            total_usd=None,
            available=False,
            missing_prices=(reason,),
        )

    @classmethod
    def from_dict(
        cls,
        payload: "CostBreakdown | Mapping[str, Any] | None",
        *,
        legacy_total: float | None = None,
    ) -> "CostBreakdown":
        """从新对象或旧的 cost_usd 字段恢复统一成本。"""
        if isinstance(payload, cls):
            return payload
        if payload:
            return cls(
                currency=str(payload.get("currency", "USD")),
                agent_usd=payload.get("agent_usd", legacy_total),
                compact_usd=payload.get("compact_usd"),
                router_usd=payload.get("router_usd"),
                judge_usd=payload.get("judge_usd"),
                task_usd=payload.get("task_usd", legacy_total),
                total_usd=payload.get("total_usd", legacy_total),
                available=bool(payload.get("available", False)),
                missing_prices=tuple(payload.get("missing_prices", ())),
            )
        if legacy_total is not None:
            return cls(
                agent_usd=legacy_total,
                task_usd=legacy_total,
                total_usd=legacy_total,
            )
        return cls.unavailable(reason="cost_not_recorded")

    def output_fields(self) -> dict[str, Any]:
        """返回日志和报告共用的新旧字段。"""
        return {
            "cost": self.to_dict(),
            "total_cost_usd": self.total_usd,
            "router_cost_usd": self.router_usd,
            "task_cost_usd": self.task_usd,
        }

    @classmethod
    def combine(cls, items: Iterable["CostBreakdown"]) -> "CostBreakdown":
        """汇总多个 Eval case，缺任一组件价格时保持不可用。"""
        items = tuple(items)
        if not items:
            return cls()
        currency = items[0].currency
        missing = tuple(
            dict.fromkeys(
                missing_price
                for item in items
                for missing_price in item.missing_prices
            )
        )

        values = {
            field_name: _sum_field(items, field_name)
            for field_name in COST_FIELDS
        }
        task_usd = _add(values["agent_usd"], values["compact_usd"])
        total_usd = _add(task_usd, values["router_usd"], values["judge_usd"])
        return cls(
            currency=currency,
            **values,
            task_usd=task_usd,
            total_usd=total_usd,
            available=all(item.available for item in items) and not missing,
            missing_prices=missing,
        )


@dataclass(frozen=True)
class _ComponentCost:
    value: float | None
    missing: tuple[str, ...] = ()


def _add(*values: float | None) -> float | None:
    return sum(values) if all(value is not None for value in values) else None


def _sum_field(
    items: tuple[CostBreakdown, ...], field_name: str
) -> float | None:
    return _add(*(getattr(item, field_name) for item in items))


def usage_total(usage: UsageTokens) -> int:
    """返回一组用量的计费 Token 总数。"""
    return sum(getattr(usage, field_name) for field_name in USAGE_FIELDS)


def _stats_usage(stats: RunStats, prefix: str = "") -> UsageTokens:
    """按 Agent、compact 或 Router 前缀读取同一组用量字段。"""
    from .loop import UsageTokens

    return UsageTokens(
        **{
            field_name: getattr(stats, f"{prefix}{field_name}")
            for field_name in USAGE_FIELDS
        }
    )


def _usage_cost(
    usage: UsageTokens,
    model: str,
    price_table: PriceTable,
    *,
    called: bool,
) -> _ComponentCost:
    """计算一次模型调用；调用过但价格缺失时返回不可用。"""
    total_tokens = usage_total(usage)
    if not called and total_tokens == 0:
        return _ComponentCost(0.0)

    price = price_table.price_for(model)
    if price is None:
        return _ComponentCost(None, (f"{model} (model price)",))

    missing = [
        f"{model}.{price_field}"
        for token_field, price_field in USAGE_PRICE_FIELDS
        if getattr(usage, token_field) > 0
        and getattr(price, price_field) is None
    ]
    if not missing and called and total_tokens == 0:
        missing = [
            f"{model}.{field_name}"
            for field_name in ("input_per_million", "output_per_million")
            if getattr(price, field_name) is None
        ]
    if missing:
        return _ComponentCost(None, tuple(missing))

    amount = (
        sum(
            getattr(usage, token_field)
            * (getattr(price, price_field) or 0)
            for token_field, price_field in USAGE_PRICE_FIELDS
        )
    ) / 1_000_000
    return _ComponentCost(amount)


def _stats_cost(
    stats: RunStats,
    price_table: PriceTable,
    model: str,
    *,
    prefix: str,
    calls_field: str,
) -> _ComponentCost:
    usage = _stats_usage(stats, prefix)
    return _usage_cost(
        usage,
        model,
        price_table,
        called=bool(getattr(stats, calls_field)) or usage_total(usage) > 0,
    )


@dataclass
class CostCalculator:
    """使用单一价格表计算 Agent、Router、compact 和 Judge 成本。"""

    settings: AgentSettings
    price_table: PriceTable

    @classmethod
    def from_settings(cls, settings: AgentSettings) -> "CostCalculator":
        return cls(
            settings=settings,
            price_table=PriceTable.load(settings.resolved_pricing_file),
        )

    def estimate_usage(self, usage: UsageTokens, model: str) -> float | None:
        """估算任意一次模型调用的成本，供 Judge 等调用方复用。"""
        return _usage_cost(
            usage,
            model,
            self.price_table,
            called=True,
        ).value

    def breakdown(
        self,
        stats: RunStats,
        judge_usage: UsageTokens | None = None,
        judge_model: str | None = None,
    ) -> CostBreakdown:
        """按固定口径生成完整成本明细。"""
        aggregate = stats.aggregate()
        selected_model = aggregate.selected_model or self.settings.main_model_name
        component_specs = (
            (selected_model, "", "turns"),
            (
                self.settings.compact_model or selected_model,
                "compact_",
                "compact_calls",
            ),
            (
                aggregate.router_model or self.settings.router_model_name,
                "router_",
                "router_calls",
            ),
        )
        agent, compact, router = (
            _stats_cost(
                aggregate,
                self.price_table,
                model,
                prefix=prefix,
                calls_field=calls_field,
            )
            for model, prefix, calls_field in component_specs
        )

        judge = _ComponentCost(0.0)
        if judge_usage is not None:
            judge = _usage_cost(
                judge_usage,
                judge_model
                or self.settings.judge_model
                or self.settings.main_model_name,
                self.price_table,
                called=True,
            )

        missing = tuple(
            dict.fromkeys(
                (
                    *agent.missing,
                    *compact.missing,
                    *router.missing,
                    *judge.missing,
                )
            )
        )
        task_usd = _add(agent.value, compact.value)
        total_usd = _add(task_usd, router.value, judge.value)
        return CostBreakdown(
            currency=self.price_table.currency,
            agent_usd=agent.value,
            compact_usd=compact.value,
            router_usd=router.value,
            judge_usd=judge.value,
            task_usd=task_usd,
            total_usd=total_usd,
            available=not missing,
            missing_prices=missing,
        )

    def estimate(self, stats: RunStats) -> float | None:
        """返回普通运行预算使用的 Agent + compact + Router 成本。"""
        return self.breakdown(stats).total_usd


__all__ = [
    "CostBreakdown",
    "CostCalculator",
    "ModelPrice",
    "PriceTable",
]
