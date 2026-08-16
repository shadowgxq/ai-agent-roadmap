from pathlib import Path

from src.client import request_timeout


def test_reads_the_existing_timeout_seconds_contract():
    assert request_timeout(Path("config.json")) == 30
