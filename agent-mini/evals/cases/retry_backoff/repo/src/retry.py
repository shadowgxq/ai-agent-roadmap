def backoff_delay(attempt: int, base_delay: float = 0.5) -> float:
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    if base_delay <= 0:
        raise ValueError("base_delay must be positive")
    return base_delay * (2 ** attempt)
