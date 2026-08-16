PRICES_CENTS = {
    "basic": 1000,
    "pro": 2000,
}


def price_cents(sku: str) -> int:
    return PRICES_CENTS[sku]
