def summarize(values: list[int]) -> dict[str, float | int]:
    total = sum(values)
    return {
        "count": len(values),
        "total": total,
        "average": total,
    }

