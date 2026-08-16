from decimal import Decimal

from src.summary import total_after_discount


def test_gold_discount_comes_from_the_discount_policy():
    assert total_after_discount(Decimal("100"), "gold") == Decimal("80")


def test_silver_discount_is_preserved():
    assert total_after_discount(Decimal("100"), "silver") == Decimal("95")


def test_unknown_tier_has_no_discount():
    assert total_after_discount(Decimal("100"), "unknown") == Decimal("100")
