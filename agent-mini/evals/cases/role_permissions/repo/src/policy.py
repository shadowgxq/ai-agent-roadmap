from .roles import DIRECT_PERMISSIONS, PARENT_ROLE


def permissions_for(role: str) -> set[str]:
    if role not in PARENT_ROLE:
        raise ValueError(f"unknown role: {role}")
    return set(DIRECT_PERMISSIONS[role])
