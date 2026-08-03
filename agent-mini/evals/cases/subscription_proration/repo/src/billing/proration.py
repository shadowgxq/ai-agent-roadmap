from datetime import date

from .cycle import cycle_days


def prorated_amount(
    monthly_cents: int,
    active_from: date,
    active_until: date,
    cycle_start: date,
    cycle_end: date,
) -> tuple[int, int]:
    if active_from < cycle_start or active_until > cycle_end:
        raise ValueError("active interval must stay inside billing cycle")
    active_days = cycle_days(active_from, active_until)
    total_days = cycle_days(cycle_start, cycle_end)
    return monthly_cents * active_days // total_days, active_days
