from src.domain.models import Preferences


def select_channels(preferences: Preferences, category: str) -> tuple[str, ...]:
    if preferences.paused:
        return ()
    return preferences.channels_by_category.get(category, ())
