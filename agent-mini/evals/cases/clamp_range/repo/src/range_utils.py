def clamp(value: int, minimum: int, maximum: int) -> int:
    if minimum > maximum:
        raise ValueError("minimum cannot exceed maximum")
    return min(max(value, minimum), maximum - 1)
