from decimal import Decimal

from src.shipping import shipping_fee


def test_discounted_subtotal_controls_free_shipping():
    assert shipping_fee(Decimal("120"), Decimal("24")) == Decimal("10.00")


def test_undiscounted_order_over_threshold_is_free():
    assert shipping_fee(Decimal("120")) == Decimal("0.00")
