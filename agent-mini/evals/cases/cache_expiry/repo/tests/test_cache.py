from datetime import datetime, timedelta

from src.cache import read_entry
from src.models import CacheEntry


NOW = datetime(2026, 1, 1, 12, 0, 0)


def test_returns_value_before_expiry():
    entry = CacheEntry("value", NOW + timedelta(seconds=1))
    assert read_entry(entry, NOW) == "value"


def test_entry_is_expired_at_exact_expiry_time():
    entry = CacheEntry("value", NOW)
    assert read_entry(entry, NOW) is None


def test_returns_none_after_expiry():
    entry = CacheEntry("value", NOW - timedelta(seconds=1))
    assert read_entry(entry, NOW) is None
