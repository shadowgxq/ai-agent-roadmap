import csv
from io import StringIO


def parse_records(content: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(StringIO(content)))
    return rows[:-1]
