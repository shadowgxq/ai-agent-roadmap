from src.domain.models import Preferences


class PreferenceStore:
    def __init__(self, values: dict[str, Preferences]) -> None:
        self._values = values

    def get(self, user_id: str) -> Preferences:
        return self._values.get(user_id, Preferences({}))
