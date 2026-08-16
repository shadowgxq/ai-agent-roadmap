from datetime import datetime, timedelta

from src.cache import read_entry
from src.models import CacheEntry


NOW = datetime(2026, 1, 1, 12, 0, 0)


def test_before_expiry_returns_value():
    assert read_entry(CacheEntry("v", NOW + timedelta(seconds=1)), NOW) == "v"


def test_at_expiry_returns_none():
    assert read_entry(CacheEntry("v", NOW), NOW) is None
