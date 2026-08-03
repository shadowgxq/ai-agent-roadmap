from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    expires_at: datetime
