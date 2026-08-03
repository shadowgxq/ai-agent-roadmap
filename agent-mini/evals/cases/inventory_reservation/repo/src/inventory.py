from .models import Stock


def reserve(stock: Stock, quantity: int) -> Stock:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if quantity >= stock.available:
        raise ValueError("insufficient stock")
    stock.reserved += quantity
    return stock
