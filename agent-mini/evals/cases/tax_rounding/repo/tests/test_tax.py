from decimal import Decimal

import pytest

from src.tax import calculate_tax


def test_rounds_half_up_to_nearest_cent():
    assert calculate_tax(Decimal("19.99"), Decimal("0.075")) == Decimal("1.50")


def test_keeps_exact_cent_value():
    assert calculate_tax(Decimal("20.00"), Decimal("0.05")) == Decimal("1.00")


def test_rejects_negative_amount():
    with pytest.raises(ValueError):
        calculate_tax(Decimal("-1"), Decimal("0.05"))
