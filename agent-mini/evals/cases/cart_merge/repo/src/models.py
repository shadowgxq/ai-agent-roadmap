from dataclasses import dataclass


@dataclass(frozen=True)
class CartLine:
    sku: str
    quantity: int
