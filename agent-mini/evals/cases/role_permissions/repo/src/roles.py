DIRECT_PERMISSIONS = {
    "viewer": {"read"},
    "editor": {"write"},
    "admin": {"manage"},
}

PARENT_ROLE = {
    "viewer": None,
    "editor": "viewer",
    "admin": "editor",
}
