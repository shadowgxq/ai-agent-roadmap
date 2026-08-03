from src.domain.models import Delivery, Notification, Preferences
from src.preferences.store import PreferenceStore
from src.services.notification import build_deliveries


def make_store(paused: bool = False) -> PreferenceStore:
    return PreferenceStore(
        {
            "U-1": Preferences(
                {
                    "marketing": ("email",),
                    "security": ("sms",),
                },
                paused=paused,
            )
        }
    )


def test_security_notification_uses_security_channel():
    deliveries = build_deliveries(
        make_store(),
        "U-1",
        Notification("security", "New login"),
    )
    assert deliveries == [Delivery("sms", "SMS: New login")]


def test_marketing_notification_uses_marketing_channel():
    deliveries = build_deliveries(
        make_store(),
        "U-1",
        Notification("marketing", "Summer sale"),
    )
    assert deliveries == [Delivery("email", "EMAIL: Summer sale")]


def test_paused_user_receives_nothing():
    assert build_deliveries(
        make_store(paused=True),
        "U-1",
        Notification("security", "New login"),
    ) == []
