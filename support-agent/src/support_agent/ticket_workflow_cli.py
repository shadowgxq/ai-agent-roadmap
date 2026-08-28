"""CLI for the W14 Session 2 ticket classification workflow."""

import argparse
import json
import sys
from typing import Any

from support_agent.config import AgentSettings
from support_agent.graphs import create_ticket_graph
from support_agent.services import create_chat_model
from support_agent.ticket_samples import (
    SESSION_02_SAMPLES,
    SESSION_03_RISK_SAMPLES,
    TicketSample,
    custom_ticket_sample,
    initial_state_for_sample,
)


ALL_FIXED_SAMPLES = (*SESSION_02_SAMPLES, *SESSION_03_RISK_SAMPLES)


def _sample_by_id(sample_id: str) -> TicketSample:
    for sample in ALL_FIXED_SAMPLES:
        if sample.sample_id == sample_id:
            return sample
    raise ValueError(f"unknown sample: {sample_id}")


def _select_samples(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> list[TicketSample]:
    if args.all_samples:
        return list(SESSION_02_SAMPLES)
    if args.risk_samples:
        return list(SESSION_03_RISK_SAMPLES)
    if args.sample is not None:
        return [_sample_by_id(args.sample)]
    if args.subject is None or args.description is None:
        parser.error("自定义输入必须同时提供 --subject 和 --description。")
    return [
        custom_ticket_sample(
            subject=args.subject,
            description=args.description,
            customer_tier=args.customer_tier,
        )
    ]


def _run_sample(
    graph: Any,
    sample: TicketSample,
    *,
    index: int,
    trace: bool,
) -> dict[str, Any]:
    state = initial_state_for_sample(sample, index=index)
    result: dict[str, Any] = dict(state)
    visited_nodes: list[str] = []

    for update in graph.stream(state, stream_mode="updates"):
        for node_name, node_update in update.items():
            visited_nodes.append(node_name)
            result.update(node_update)
            if trace:
                print(
                    "[trace] "
                    + json.dumps(
                        {
                            "sample_id": sample.sample_id,
                            "node": node_name,
                            "updates": node_update,
                        },
                        ensure_ascii=False,
                        default=_json_default,
                    ),
                    file=sys.stderr,
                )

    entered_clarification = "build_clarification" in visited_nodes
    entered_response = "response_subgraph" in visited_nodes
    actual_branch = (
        "clarification"
        if entered_clarification
        else "response"
        if entered_response
        else "terminal_or_error"
    )

    if sample.expected_clarification is None:
        assertion = {
            "status": "not_applicable",
            "message": "自定义输入未预设分支。",
        }
    else:
        expected_branch = (
            "clarification" if sample.expected_clarification else "response"
        )
        passed = (
            entered_clarification and not entered_response
            if sample.expected_clarification
            else entered_response and not entered_clarification
        )
        assertion: dict[str, Any] = {
            "status": "passed" if passed else "failed",
            "expected_branch": expected_branch,
            "actual_branch": actual_branch,
            "message": (
                "信息缺失未进入 response_subgraph。"
                if sample.expected_clarification and passed
                else "完整输入进入了 response_subgraph 边界。"
                if not sample.expected_clarification and passed
                else "实际节点路径与预期不符。"
            ),
        }
        if sample.expected_risk_level is not None:
            risk_passed = (
                result.get("risk_level") == sample.expected_risk_level
                and result.get("requires_approval")
                == sample.expected_requires_approval
            )
            assertion["risk"] = {
                "status": "passed" if risk_passed else "failed",
                "expected_level": sample.expected_risk_level,
                "actual_level": result.get("risk_level"),
                "expected_requires_approval": sample.expected_requires_approval,
                "actual_requires_approval": result.get("requires_approval"),
            }
            if not risk_passed:
                assertion["status"] = "failed"

    return {
        "sample_id": sample.sample_id,
        "notes": sample.notes,
        "category": result.get("category"),
        "priority": result.get("priority"),
        "missing_fields": result.get("missing_fields", []),
        "needs_clarification": bool(result.get("missing_fields")),
        "evidence_refs": result.get("evidence_refs", []),
        "visited_nodes": visited_nodes,
        "status": result.get("status"),
        "error_code": result.get("error_code"),
        "draft_response": result.get("draft_response"),
        "risk_level": result.get("risk_level"),
        "risk_reasons": result.get("risk_reasons", []),
        "requires_approval": result.get("requires_approval"),
        "assertion": assertion,
    }


def _json_default(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump()  # type: ignore[no-any-return]
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the W14 Session 2 ticket classification workflow."
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument(
        "--sample",
        choices=[sample.sample_id for sample in ALL_FIXED_SAMPLES],
        help="Run one fixed Session 2 or Session 3 sample.",
    )
    selector.add_argument(
        "--all-samples",
        action="store_true",
        help="Run all eight fixed samples and check their branches.",
    )
    selector.add_argument(
        "--risk-samples",
        action="store_true",
        help="Run the two Session 3 risk acceptance samples.",
    )
    selector.add_argument(
        "--subject",
        help="Subject for a custom ticket; use together with --description.",
    )
    parser.add_argument(
        "--description", help="Description for a custom ticket.")
    parser.add_argument("--customer-tier", default="standard")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Print node updates to stderr while the graph runs.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.description is not None and args.subject is None:
        parser.error("--description 只能和 --subject 一起使用。")

    samples = _select_samples(args, parser)
    settings = AgentSettings()
    model = create_chat_model(settings)
    graph = create_ticket_graph(model)

    results: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        try:
            results.append(
                _run_sample(
                    graph,
                    sample,
                    index=index,
                    trace=args.trace,
                )
            )
        except Exception as exc:  # noqa: BLE001 - CLI must report per-sample failures.
            results.append(
                {
                    "sample_id": sample.sample_id,
                    "notes": sample.notes,
                    "assertion": {
                        "status": "error",
                        "message": f"{type(exc).__name__}: {exc}",
                    },
                }
            )

    all_passed = all(
        item["assertion"]["status"] in {"passed", "not_applicable"}
        for item in results
    )
    payload: dict[str, Any] = {
        "sample_count": len(results),
        "all_assertions_passed": all_passed,
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
