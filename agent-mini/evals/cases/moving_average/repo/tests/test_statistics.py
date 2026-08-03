import pytest

from src.statistics import moving_average


def test_uses_available_values_until_window_is_full():
    assert moving_average([2, 4, 8, 10], 3) == [2, 3, pytest.approx(14 / 3), pytest.approx(22 / 3)]


def test_empty_input_returns_empty_output():
    assert moving_average([], 3) == []


def test_rejects_invalid_window():
    with pytest.raises(ValueError):
        moving_average([1], 0)
