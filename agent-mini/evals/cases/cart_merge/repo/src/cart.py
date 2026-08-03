from .models import CartLine


def merge_lines(lines: list[CartLine]) -> list[CartLine]:
    quantities: dict[str, int] = {}
    for line in lines:
        if line.quantity <= 0:
            raise ValueError("quantity must be positive")
        quantities[line.sku] = line.quantity
    return [CartLine(sku, quantity) for sku, quantity in quantities.items()]
