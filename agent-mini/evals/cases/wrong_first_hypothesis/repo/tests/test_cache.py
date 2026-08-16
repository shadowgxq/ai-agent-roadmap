from src.cache import get_or_compute


def test_cached_zero_is_not_recomputed():
    calls = 0

    def loader() -> int:
        nonlocal calls
        calls += 1
        return 99

    assert get_or_compute({"count": 0}, "count", loader) == 0
    assert calls == 0


def test_cached_false_and_none_are_valid_values():
    assert get_or_compute({"enabled": False}, "enabled", lambda: True) is False
    assert get_or_compute({"value": None}, "value", lambda: "new") is None
