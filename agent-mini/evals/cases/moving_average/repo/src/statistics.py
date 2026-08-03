def moving_average(values: list[float], window: int) -> list[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    averages: list[float] = []
    for index in range(len(values)):
        current = values[max(0, index - window + 1): index + 1]
        averages.append(sum(current) / window)
    return averages
