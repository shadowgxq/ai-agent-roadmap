from decimal import Decimal


FREE_SHIPPING_THRESHOLD = Decimal("100.00")
STANDARD_SHIPPING = Decimal("10.00")


def shipping_fee(subtotal: Decimal, discount: Decimal = Decimal("0")) -> Decimal:
    if subtotal < 0 or discount < 0 or discount > subtotal:
        raise ValueError("invalid subtotal or discount")
    discounted_subtotal = subtotal
    if discounted_subtotal >= FREE_SHIPPING_THRESHOLD:
        return Decimal("0.00")
    return STANDARD_SHIPPING
