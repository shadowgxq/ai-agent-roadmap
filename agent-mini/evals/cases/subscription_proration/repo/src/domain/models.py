from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Subscription:
    plan_code: str
    active_from: date
    active_until: date


@dataclass(frozen=True)
class Invoice:
    plan_code: str
    amount_cents: int
    service_days: int
