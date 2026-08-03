import pytest

from src.retry import backoff_delay


def test_first_attempt_uses_base_delay():
    assert backoff_delay(1) == 0.5


def test_delay_doubles_each_attempt():
    assert backoff_delay(2) == 1.0
    assert backoff_delay(3) == 2.0


def test_rejects_zero_attempt():
    with pytest.raises(ValueError):
        backoff_delay(0)
