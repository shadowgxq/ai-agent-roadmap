def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if any(start > end for start, end in intervals):
        raise ValueError("interval start cannot exceed end")
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if not merged or start >= merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]
