def channels_for(severity: str) -> list[str]:
    if severity == "critical":
        return ["pager"]
    return ["email"]
