from src.pagination import paginate


def test_returns_full_page():
    items = ["a", "b", "c", "d", "e"]
    assert paginate(items, page=0, page_size=3) == ["a", "b", "c"]


def test_returns_last_partial_page():
    items = ["a", "b", "c", "d", "e"]
    assert paginate(items, page=1, page_size=3) == ["d", "e"]
