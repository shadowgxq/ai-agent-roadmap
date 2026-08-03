from decimal import Decimal

from src.domain.models import Customer


RATES = {
    "regular": Decimal("0"),
    "gold": Decimal("0.20"),
}


def discount_for(customer: Customer, subtotal: Decimal) -> Decimal:
    if customer.tier not in RATES:
        raise ValueError(f"unknown customer tier: {customer.tier}")
    return subtotal * RATES[customer.tier]
