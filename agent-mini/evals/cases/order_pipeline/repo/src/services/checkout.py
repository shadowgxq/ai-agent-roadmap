from decimal import Decimal, ROUND_HALF_UP

from src.domain.models import CartLine, CheckoutResult, Customer
from src.pricing.discounts import discount_for
from src.shipping.policy import shipping_fee


CENT = Decimal("0.01")
TAX_RATE = Decimal("0.10")


def checkout(customer: Customer, lines: list[CartLine]) -> CheckoutResult:
    if not lines or any(line.quantity <= 0 for line in lines):
        raise ValueError("checkout requires positive cart lines")

    subtotal = sum(
        (line.unit_price * line.quantity for line in lines),
        Decimal("0"),
    )
    discount = discount_for(customer, subtotal)
    discounted_subtotal = subtotal - discount
    shipping = shipping_fee(subtotal)
    tax = (discounted_subtotal * TAX_RATE).quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )
    total = (discounted_subtotal + shipping + tax).quantize(CENT)
    return CheckoutResult(subtotal, discount, shipping, tax, total)
