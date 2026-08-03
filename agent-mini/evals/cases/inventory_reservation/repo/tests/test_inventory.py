import pytest

from src.inventory import reserve
from src.models import Stock


def test_reserves_part_of_available_stock():
    stock = reserve(Stock("A-1", on_hand=10), 4)
    assert stock.reserved == 4
    assert stock.available == 6


def test_can_reserve_exactly_all_available_stock():
    stock = reserve(Stock("A-1", on_hand=10, reserved=3), 7)
    assert stock.reserved == 10
    assert stock.available == 0


def test_rejects_more_than_available_stock():
    with pytest.raises(ValueError):
        reserve(Stock("A-1", on_hand=5), 6)
