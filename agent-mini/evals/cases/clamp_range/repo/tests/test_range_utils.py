import pytest

from src.range_utils import clamp


def test_clamps_below_minimum():
    assert clamp(-2, 0, 10) == 0


def test_keeps_value_inside_range():
    assert clamp(6, 0, 10) == 6


def test_maximum_is_inclusive():
    assert clamp(12, 0, 10) == 10


def test_rejects_invalid_range():
    with pytest.raises(ValueError):
        clamp(3, 5, 4)
