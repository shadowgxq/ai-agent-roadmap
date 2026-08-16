from src.catalog import price_cents


def format_invoice_total(sku: str, quantity: int) -> str:
    total_cents = price_cents(sku) * quantity
    return f"${total_cents / 100:.2f}"
