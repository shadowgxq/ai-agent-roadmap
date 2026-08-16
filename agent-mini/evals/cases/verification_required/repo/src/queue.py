from collections.abc import MutableSequence
from typing import TypeVar


T = TypeVar("T")


def pop_next(queue: MutableSequence[T]) -> T | None:
    return queue.pop(0)
