from decimal import Decimal

from src.domain.models import CartLine, Customer
from src.services.checkout import checkout


def test_discounted_subtotal_controls_free_shipping():
    result = checkout(
        Customer("C-1", tier="gold"),
        [CartLine("A", Decimal("60.00"), 2)],
    )
    assert result.subtotal == Decimal("120.00")
    assert result.discount == Decimal("24.0000")
    assert result.shipping == Decimal("10.00")
    assert result.tax == Decimal("9.60")
    assert result.total == Decimal("115.60")


def test_regular_customer_over_threshold_gets_free_shipping():
    result = checkout(
        Customer("C-2"),
        [CartLine("B", Decimal("120.00"), 1)],
    )
    assert result.shipping == Decimal("0.00")
    assert result.total == Decimal("132.00")
