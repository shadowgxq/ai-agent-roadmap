from src.domain.models import Delivery


def email_delivery(message: str) -> Delivery:
    return Delivery("email", f"EMAIL: {message}")
