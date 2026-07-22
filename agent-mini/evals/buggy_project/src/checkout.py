from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


@dataclass(frozen=True)
class CartLine:
    name: str
    unit_price: Decimal
    quantity: int


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_order_total(
    lines: list[CartLine],
    tax_rate: Decimal,
    coupon_percent: Decimal = Decimal("0"),
) -> dict[str, Decimal]:
    """Return subtotal, discount, tax, shipping, and final total for a cart."""
    subtotal = sum(
        (line.unit_price * line.quantity for line in lines),
        Decimal("0"),
    )
    discount = subtotal * coupon_percent / Decimal("100")
    taxable_total = subtotal - discount
    tax = taxable_total * tax_rate
    shipping = Decimal("0") if taxable_total >= Decimal("100") else Decimal("10")
    total = taxable_total + tax + shipping
    return {
        "subtotal": _money(subtotal),
        "discount": _money(discount),
        "tax": _money(tax),
        "shipping": _money(shipping),
        "total": _money(total),
    }
