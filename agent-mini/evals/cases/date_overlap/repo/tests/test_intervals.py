from datetime import datetime

import pytest

from src.intervals import overlaps


def at(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour)


def test_detects_overlap():
    assert overlaps(at(9), at(12), at(11), at(14)) is True


def test_touching_half_open_intervals_do_not_overlap():
    assert overlaps(at(9), at(12), at(12), at(14)) is False


def test_detects_separate_intervals():
    assert overlaps(at(9), at(10), at(11), at(12)) is False


def test_rejects_empty_interval():
    with pytest.raises(ValueError):
        overlaps(at(9), at(9), at(10), at(11))
