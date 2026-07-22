def paginate(items: list[str], page: int, page_size: int) -> list[str]:
    start = page * page_size
    end = start + page_size
    return items[start:end]
