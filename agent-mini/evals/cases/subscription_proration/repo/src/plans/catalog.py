PLAN_PRICES = {
    "basic": 3000,
    "pro": 6000,
}


def monthly_price(plan_code: str) -> int:
    if plan_code not in PLAN_PRICES:
        raise ValueError(f"unknown plan: {plan_code}")
    return PLAN_PRICES[plan_code]
