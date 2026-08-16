import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    with Path(args.input_csv).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    print(json.dumps(rows, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
