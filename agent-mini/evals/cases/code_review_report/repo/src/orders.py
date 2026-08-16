from src.pricing import PRICES


def order_total(sku: str, quantity: int) -> float:
    return PRICES[sku] * quantity
