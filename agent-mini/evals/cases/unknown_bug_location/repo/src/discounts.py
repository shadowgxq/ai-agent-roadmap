from decimal import Decimal


DISCOUNT_RATES = {
    "gold": Decimal("0.20"),
    "silver": Decimal("0.05"),
}


def discount_rate(tier: str) -> Decimal:
    return DISCOUNT_RATES.get(tier, Decimal("0"))
