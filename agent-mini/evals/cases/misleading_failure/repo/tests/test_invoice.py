from src.invoice import format_invoice_total


def test_basic_invoice_total():
    assert format_invoice_total("basic", 2) == "$20.00"


def test_pro_invoice_total():
    assert format_invoice_total("pro", 2) == "$50.00"
