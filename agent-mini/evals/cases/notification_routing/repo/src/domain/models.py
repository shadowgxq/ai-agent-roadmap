from dataclasses import dataclass


@dataclass(frozen=True)
class Notification:
    category: str
    message: str


@dataclass(frozen=True)
class Preferences:
    channels_by_category: dict[str, tuple[str, ...]]
    paused: bool = False


@dataclass(frozen=True)
class Delivery:
    channel: str
    payload: str
