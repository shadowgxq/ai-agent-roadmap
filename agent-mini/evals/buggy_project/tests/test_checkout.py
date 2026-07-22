from decimal import Decimal

from src.checkout import CartLine, calculate_order_total


def test_discount_is_applied_before_tax_and_free_shipping_threshold_uses_discounted_total():
    lines = [CartLine("keyboard", Decimal("120.00"), 1)]
    result = calculate_order_total(
        lines,
        tax_rate=Decimal("0.10"),
        coupon_percent=Decimal("20"),
    )

    assert result == {
        "subtotal": Decimal("120.00"),
        "discount": Decimal("24.00"),
        "tax": Decimal("9.60"),
        "shipping": Decimal("10.00"),
        "total": Decimal("115.60"),
    }


def test_shipping_is_free_when_discounted_subtotal_reaches_100():
    lines = [CartLine("monitor", Decimal("125.00"), 1)]
    result = calculate_order_total(
        lines,
        tax_rate=Decimal("0.08"),
        coupon_percent=Decimal("20"),
    )

    assert result["shipping"] == Decimal("0.00")
    assert result["tax"] == Decimal("8.00")
    assert result["total"] == Decimal("108.00")


def test_rounds_each_money_field_with_half_up():
    lines = [CartLine("cable", Decimal("0.335"), 3)]
    result = calculate_order_total(
        lines,
        tax_rate=Decimal("0.10"),
        coupon_percent=Decimal("0"),
    )

    assert result["subtotal"] == Decimal("1.01")
    assert result["tax"] == Decimal("0.10")
    assert result["total"] == Decimal("11.11")
