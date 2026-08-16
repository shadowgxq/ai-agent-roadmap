ROLE_ACTIONS = {
    "viewer": {"read"},
    "editor": {"read"},
    "admin": {"read", "write", "delete"},
}


def allowed(role: str, action: str) -> bool:
    return action in ROLE_ACTIONS.get(role, set())
