def normalize_username(value: str) -> str:
    """Return a lowercase username with normalized whitespace."""
    return value.strip().lower()
