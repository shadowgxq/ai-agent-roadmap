from decimal import Decimal, ROUND_DOWN


CENT = Decimal("0.01")


def calculate_tax(amount: Decimal, rate: Decimal) -> Decimal:
    if amount < 0 or rate < 0:
        raise ValueError("amount and rate must be non-negative")
    return (amount * rate).quantize(CENT, rounding=ROUND_DOWN)
