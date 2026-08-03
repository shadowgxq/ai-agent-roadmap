from datetime import date, timedelta

from src.billing.proration import prorated_amount
from src.domain.models import Invoice, Subscription
from src.plans.catalog import monthly_price


def create_invoice(
    subscription: Subscription,
    cycle_start: date,
    cycle_end: date,
) -> Invoice:
    amount, days = prorated_amount(
        monthly_price(subscription.plan_code),
        subscription.active_from,
        subscription.active_until + timedelta(days=1),
        cycle_start,
        cycle_end,
    )
    return Invoice(subscription.plan_code, amount, days)
