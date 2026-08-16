from src.queue import pop_next


def test_empty_queue_returns_none():
    assert pop_next([]) is None


def test_items_are_removed_in_fifo_order():
    queue = ["first", "second"]
    assert pop_next(queue) == "first"
    assert pop_next(queue) == "second"
    assert queue == []
