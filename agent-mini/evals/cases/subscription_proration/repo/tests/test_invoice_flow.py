from datetime import date

from src.domain.models import Invoice, Subscription
from src.services.invoice import create_invoice


CYCLE_START = date(2026, 1, 1)
CYCLE_END = date(2026, 1, 31)


def test_partial_subscription_uses_exclusive_active_until():
    subscription = Subscription(
        "basic",
        active_from=date(2026, 1, 11),
        active_until=date(2026, 1, 21),
    )
    assert create_invoice(subscription, CYCLE_START, CYCLE_END) == Invoice(
        "basic",
        1000,
        10,
    )


def test_full_cycle_bills_monthly_price():
    subscription = Subscription("pro", CYCLE_START, CYCLE_END)
    assert create_invoice(subscription, CYCLE_START, CYCLE_END) == Invoice(
        "pro",
        6000,
        30,
    )
