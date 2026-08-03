from datetime import datetime


def overlaps(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    if start_a >= end_a or start_b >= end_b:
        raise ValueError("interval end must be after start")
    return start_a <= end_b and start_b <= end_a
