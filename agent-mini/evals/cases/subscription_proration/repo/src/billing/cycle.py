from datetime import date


def cycle_days(start: date, end: date) -> int:
    if end <= start:
        raise ValueError("cycle end is exclusive and must follow start")
    return (end - start).days
