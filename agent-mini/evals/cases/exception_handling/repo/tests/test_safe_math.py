import pytest

from src.safe_math import safe_divide


def test_divides_regular_numbers():
    assert safe_divide(10, 2) == 5


def test_returns_none_when_divisor_is_zero():
    assert safe_divide(10, 0) is None


def test_preserves_negative_results():
    assert safe_divide(-9, 3) == pytest.approx(-3)
