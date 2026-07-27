def allocate_cents(total_cents, weights):
    total_weight = sum(weights)
    return [
        round(total_cents * weight / total_weight)
        for weight in weights
    ]
