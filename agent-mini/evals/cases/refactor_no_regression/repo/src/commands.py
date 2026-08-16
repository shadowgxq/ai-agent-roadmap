def parse_command(line: str) -> list[str]:
    return line.strip().split()


def parse_script(text: str) -> list[list[str]]:
    return [parse_command(line) for line in text.splitlines() if line.strip()]
