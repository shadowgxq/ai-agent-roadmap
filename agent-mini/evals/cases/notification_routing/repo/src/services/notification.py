from src.channels.email import email_delivery
from src.channels.sms import sms_delivery
from src.domain.models import Delivery, Notification
from src.preferences.store import PreferenceStore
from src.routing.selector import select_channels


BUILDERS = {
    "email": email_delivery,
    "sms": sms_delivery,
}


def build_deliveries(
    store: PreferenceStore,
    user_id: str,
    notification: Notification,
) -> list[Delivery]:
    preferences = store.get(user_id)
    channels = select_channels(preferences, "marketing")
    return [BUILDERS[channel](notification.message) for channel in channels]
