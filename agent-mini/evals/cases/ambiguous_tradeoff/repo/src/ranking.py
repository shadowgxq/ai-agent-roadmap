def rank_scores(rows: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return sorted(rows, key=lambda row: row[1])

