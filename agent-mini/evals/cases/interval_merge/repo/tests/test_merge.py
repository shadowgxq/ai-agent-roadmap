import pytest

from src.merge import merge_intervals


def test_merges_overlapping_intervals():
    assert merge_intervals([(1, 5), (3, 8)]) == [(1, 8)]


def test_merges_touching_integer_intervals():
    assert merge_intervals([(1, 3), (3, 6), (9, 10)]) == [(1, 6), (9, 10)]


def test_sorts_intervals_before_merging():
    assert merge_intervals([(5, 7), (1, 2)]) == [(1, 2), (5, 7)]


def test_rejects_reversed_interval():
    with pytest.raises(ValueError):
        merge_intervals([(4, 2)])
