from dataclasses import dataclass


@dataclass(frozen=True)
class UserProfile:
    name: str
    email: str


def render_profile(profile: UserProfile) -> str:
    return f"{profile.name} <{profile.email}>"
