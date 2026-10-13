"""Run local W21 Graph fixtures or inspect recorded observations. Never calls a model provider."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from support_agent.application.security import redact
from support_agent.evaluation.catalog import load_catalog
from support_agent.evaluation.offline import execute_offline
from support_agent.evaluation.report import make_report


async def run_offline(manifest, cases, corpus, top_k=5):
    batch_id = uuid4().hex[:12]
    return [await asyncio.wait_for(execute_offline(case, manifest, corpus, batch_id, top_k=top_k),
                                   timeout=manifest["budget"]["timeout_seconds"]) for case in cases]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recorded", type=Path, help="JSON observations collected by an independently authorized runtime")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--w19-report", type=Path)
    parser.add_argument("--w18-report", type=Path)
    args = parser.parse_args()
    manifest, cases, corpus = load_catalog()
    observations = json.loads(args.recorded.read_text())["observations"] if args.recorded else asyncio.run(run_offline(manifest, cases, corpus))
    report = make_report(manifest, cases, observations)
    report["separate_baselines"] = {"w19_retrieval": json.loads(args.w19_report.read_text()) if args.w19_report else None,
                                    "w18_multi_agent": json.loads(args.w18_report.read_text()) if args.w18_report else None}
    args.output.write_text(json.dumps(redact(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"observations", "results", "separate_baselines"}}, indent=2))
    raise SystemExit(0 if report["passed_count"] == report["case_count"] else 1)


if __name__ == "__main__":
    main()
