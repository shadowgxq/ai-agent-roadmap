"""比较两次 Eval 报告，输出提升、回归和失败分类变化。"""

from __future__ import annotations
from evals.analysis import (
    aggregate_usage,
    summarize_buckets,
    summarize_failure_categories,
)

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from src.agent.cost import CostBreakdown

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_report(path: Path) -> dict[str, Any]:
    """读取并校验最小 Eval 报告结构。"""
    with path.expanduser().resolve().open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("results"), list
    ):
        raise ValueError(f"不是有效的 Eval 报告: {path}")
    return payload


def _delta(candidate: float | int | None, baseline: float | int | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return round(float(candidate) - float(baseline), 4)


def _report_cost(report: dict[str, Any]) -> dict[str, float | None]:
    """读取新 cost 对象，并兼容旧报告的平铺费用字段。"""
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    legacy_total = summary.get(
        "cost_usd",
        summary.get("total_cost_usd", report.get("total_cost_usd")),
    )
    nested = report.get("cost")
    if not isinstance(nested, dict):
        nested = summary.get("cost")
    cost = CostBreakdown.from_dict(
        nested if isinstance(nested, dict) else {
            "router_usd": summary.get("router_cost_usd"),
        },
        legacy_total=legacy_total,
    )
    return {
        "total_usd": cost.total_usd,
        "avg_total_usd": summary.get("avg_cost_usd"),
        "agent_usd": cost.agent_usd,
        "compact_usd": cost.compact_usd,
        "router_usd": cost.router_usd,
        "judge_usd": cost.judge_usd,
    }


def compare_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """返回两份报告的结构化比较结果。"""
    baseline_results = baseline["results"]
    candidate_results = candidate["results"]
    baseline_buckets = summarize_buckets(baseline_results)
    candidate_buckets = summarize_buckets(candidate_results)
    bucket_names = sorted(set(baseline_buckets) | set(candidate_buckets))

    buckets: dict[str, Any] = {}
    regressions: list[str] = []
    for name in bucket_names:
        before = baseline_buckets.get(name, {})
        after = candidate_buckets.get(name, {})
        before_rate = before.get("objective_pass_rate")
        after_rate = after.get("objective_pass_rate")
        rate_delta = _delta(after_rate, before_rate)
        buckets[name] = {
            "baseline": before,
            "candidate": after,
            "objective_pass_rate_delta": rate_delta,
        }
        if rate_delta is not None and rate_delta < 0:
            regressions.append(
                f"{name}.objective_pass_rate {before_rate} -> {after_rate}"
            )

        before_judge = before.get("judge_averages", {})
        after_judge = after.get("judge_averages", {})
        for dimension in sorted(set(before_judge) | set(after_judge)):
            judge_delta = _delta(
                after_judge.get(dimension), before_judge.get(dimension)
            )
            if judge_delta is not None and judge_delta <= -0.5:
                regressions.append(
                    f"{name}.{dimension} "
                    f"{before_judge[dimension]} -> {after_judge[dimension]}"
                )

    before_failure = summarize_failure_categories(baseline_results)
    after_failure = summarize_failure_categories(candidate_results)
    failure_categories = {}
    for category in sorted(set(before_failure) | set(after_failure)):
        before_count = before_failure.get(category, 0)
        after_count = after_failure.get(category, 0)
        failure_categories[category] = {
            "baseline": before_count,
            "candidate": after_count,
            "delta": after_count - before_count,
        }

    before_usage = aggregate_usage(baseline_results)
    after_usage = aggregate_usage(candidate_results)
    usage = {
        field: {
            "baseline": before_usage.get(field),
            "candidate": after_usage.get(field),
            "delta": _delta(
                after_usage.get(field),
                before_usage.get(field),
            ),
        }
        for field in (
            "total_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "cache_read_ratio",
        )
    }
    baseline_cost = _report_cost(baseline)
    candidate_cost = _report_cost(candidate)
    cost = {
        field: {
            "baseline": baseline_cost[field],
            "candidate": candidate_cost[field],
            "delta": _delta(candidate_cost[field], baseline_cost[field]),
        }
        for field in (
            "total_usd",
            "avg_total_usd",
            "agent_usd",
            "compact_usd",
            "router_usd",
            "judge_usd",
        )
    }

    return {
        "baseline": baseline.get("experiment", "baseline"),
        "candidate": candidate.get("experiment", "candidate"),
        "buckets": buckets,
        "failure_categories": failure_categories,
        "usage": usage,
        "cost": cost,
        "regressions": regressions,
    }


def _format_rate(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "n/a"


def render_comparison(comparison: dict[str, Any]) -> str:
    """渲染适合终端阅读的实验对比。"""
    lines = [
        "Eval Experiment Comparison",
        "=" * 32,
        f"Baseline: {comparison['baseline']}",
        f"Candidate: {comparison['candidate']}",
        "Buckets",
    ]
    for name, data in comparison["buckets"].items():
        before = data["baseline"].get("objective_pass_rate")
        after = data["candidate"].get("objective_pass_rate")
        delta = data["objective_pass_rate_delta"]
        delta_text = f"{delta:+.4f}" if delta is not None else "n/a"
        lines.append(
            f"  {name}: {_format_rate(before)} -> "
            f"{_format_rate(after)} (delta={delta_text})"
        )
    lines.append("Failure taxonomy")
    if comparison["failure_categories"]:
        for category, data in comparison["failure_categories"].items():
            lines.append(
                f"  {category}: {data['baseline']} -> "
                f"{data['candidate']} (delta={data['delta']:+d})"
            )
    else:
        lines.append("  none")
    lines.append("Usage")
    for field, data in comparison["usage"].items():
        lines.append(
            f"  {field}: {data['baseline']} -> {data['candidate']}"
        )
    lines.append("Cost")
    for field, data in comparison["cost"].items():
        lines.append(
            f"  {field}: {data['baseline']} -> {data['candidate']} "
            f"(delta={data['delta']})"
        )
    lines.append("Regressions")
    if comparison["regressions"]:
        lines.extend(f"  - {item}" for item in comparison["regressions"])
    else:
        lines.append("  none")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="比较两次 agent-mini Eval 报告")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="发现客观通过率下降或 Judge 下降时返回退出码 1",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    comparison = compare_reports(
        load_report(args.baseline),
        load_report(args.candidate),
    )
    if args.as_json:
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
    else:
        print(render_comparison(comparison))
    return 1 if args.fail_on_regression and comparison["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "compare_reports",
    "load_report",
    "render_comparison",
]
