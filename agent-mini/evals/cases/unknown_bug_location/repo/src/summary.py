from decimal import Decimal

from src.discounts import discount_rate


def total_after_discount(amount: Decimal, tier: str) -> Decimal:
    # The calculation is intentionally duplicated incorrectly here.
    rate = Decimal("0.10") if tier == "gold" else Decimal("0.05")
    return amount - amount * rate
