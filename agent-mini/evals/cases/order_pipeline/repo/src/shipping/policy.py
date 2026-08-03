from decimal import Decimal


FREE_SHIPPING_THRESHOLD = Decimal("100.00")
STANDARD_SHIPPING = Decimal("10.00")


def shipping_fee(discounted_subtotal: Decimal) -> Decimal:
    if discounted_subtotal < 0:
        raise ValueError("subtotal must be non-negative")
    if discounted_subtotal >= FREE_SHIPPING_THRESHOLD:
        return Decimal("0.00")
    return STANDARD_SHIPPING
