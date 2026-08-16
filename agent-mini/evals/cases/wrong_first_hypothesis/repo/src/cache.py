from collections.abc import Callable
from typing import Any


def get_or_compute(
    cache: dict[str, Any],
    key: str,
    loader: Callable[[], Any],
) -> Any:
    if cache.get(key):
        return cache[key]
    value = loader()
    cache[key] = value
    return value
