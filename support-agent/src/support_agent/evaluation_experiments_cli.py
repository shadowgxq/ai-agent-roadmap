import argparse
import asyncio
import json
from pathlib import Path
from support_agent.evaluation.experiments import run_experiments


def main():
    parser = argparse.ArgumentParser(description="Run offline W21 single-variable experiments; no providers or services")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_experiments())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["comparisons"], indent=2))


if __name__ == "__main__":
    main()
