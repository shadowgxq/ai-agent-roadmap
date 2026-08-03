from src.domain.models import Delivery


def sms_delivery(message: str) -> Delivery:
    return Delivery("sms", f"SMS: {message}")
