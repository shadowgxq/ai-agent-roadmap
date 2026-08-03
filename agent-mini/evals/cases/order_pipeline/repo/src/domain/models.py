from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CartLine:
    sku: str
    unit_price: Decimal
    quantity: int


@dataclass(frozen=True)
class Customer:
    customer_id: str
    tier: str = "regular"


@dataclass(frozen=True)
class CheckoutResult:
    subtotal: Decimal
    discount: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal
