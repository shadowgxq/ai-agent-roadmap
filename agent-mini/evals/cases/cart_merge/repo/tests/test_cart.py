import pytest

from src.cart import merge_lines
from src.models import CartLine


def test_combines_duplicate_skus():
    lines = [CartLine("A", 2), CartLine("B", 1), CartLine("A", 3)]
    assert merge_lines(lines) == [CartLine("A", 5), CartLine("B", 1)]


def test_keeps_unique_lines():
    assert merge_lines([CartLine("A", 2)]) == [CartLine("A", 2)]


def test_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        merge_lines([CartLine("A", 0)])
