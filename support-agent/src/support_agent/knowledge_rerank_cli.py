"""Inspect existing reports only; no model calls or automatic reranker installation."""

import argparse
import json
from pathlib import Path

from support_agent.knowledge.reranking import compare_reranking, diagnose_ranking


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--max-latency-ratio", type=float, default=1.5)
    parser.add_argument("--max-extra-cost-usd", type=float, default=0.01)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text())
    result = (compare_reranking(baseline, json.loads(args.candidate.read_text()),
                               max_latency_ratio=args.max_latency_ratio,
                               max_extra_cost_usd=args.max_extra_cost_usd)
              if args.candidate else diagnose_ranking(baseline))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
