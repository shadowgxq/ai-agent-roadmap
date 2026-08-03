from datetime import datetime
from typing import Any

from .models import CacheEntry


def read_entry(entry: CacheEntry, now: datetime) -> Any | None:
    if now > entry.expires_at:
        return None
    return entry.value
