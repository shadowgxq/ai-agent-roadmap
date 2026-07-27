def take_page(items: list[str], page: int, page_size: int) -> list[str]:
    """Return one zero-based page from a list of items."""
    start = page * page_size
    end = start + page_size - 1
    return items[start:end]
