import json
from pathlib import Path


def request_timeout(config_path: str | Path) -> int:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return int(config["timeout"])
