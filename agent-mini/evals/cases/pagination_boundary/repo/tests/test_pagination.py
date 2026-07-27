from src.pagination import take_page


def test_returns_a_full_page():
    assert take_page(["a", "b", "c", "d"], page=0, page_size=2) == [
        "a",
        "b",
    ]


def test_returns_a_later_page():
    assert take_page(["a", "b", "c", "d"], page=1, page_size=2) == [
        "c",
        "d",
    ]


def test_returns_a_partial_last_page():
    assert take_page(["a", "b", "c", "d", "e"], page=1, page_size=3) == [
        "d",
        "e",
    ]
