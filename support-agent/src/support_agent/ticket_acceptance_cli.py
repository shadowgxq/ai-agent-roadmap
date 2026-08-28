"""One-click W14 Session 5 acceptance runner."""

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from support_agent.config import AgentSettings
from support_agent.models import AgentEvent
from support_agent.services import GraphEventAdapter, create_chat_model
from support_agent.graphs import create_ticket_graph
from support_agent.ticket_samples import (
    SESSION_05_SAMPLES,
    TicketSample,
    initial_state_for_sample,
)


FAILURE_CATEGORIES = (
    "classification",
    "clarification",
    "evidence",
    "risk",
    "protocol",
)
VALID_CATEGORIES = {"billing", "account", "product", "technical", "other"}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}
KNOWN_NODE_NAMES = {
    "normalize_ticket",
    "classify_ticket",
    "build_clarification",
    "response_subgraph",
    "retrieve_policy_stub",
    "draft_response",
    "assess_risk",
    "finalize",
}


def _chain_output(raw_event: Mapping[str, Any]) -> dict[str, Any]:
    data = raw_event.get("data")
    if not isinstance(data, Mapping):
        return {}
    output = data.get("output")
    if not isinstance(output, Mapping):
        return {}
    return dict(output)


def _failure(
    failures: list[dict[str, str]],
    category: str,
    message: str,
) -> None:
    failures.append({"category": category, "message": message})


def _source_ids(evidence_refs: object) -> list[str]:
    if not isinstance(evidence_refs, list):
        return []
    source_ids: list[str] = []
    for ref in evidence_refs:
        source_id = (
            ref.get("source_id")
            if isinstance(ref, Mapping)
            else getattr(ref, "source_id", None)
        )
        if isinstance(source_id, str) and source_id:
            source_ids.append(source_id)
    return source_ids


def evaluate_case(
    sample: TicketSample,
    result: Mapping[str, Any],
    visited_nodes: list[str],
    events: list[AgentEvent],
) -> list[dict[str, str]]:
    """Return objective failures for one fixture without changing graph state."""

    failures: list[dict[str, str]] = []
    actual_category = result.get("category")
    if actual_category not in VALID_CATEGORIES:
        _failure(failures, "classification", "category 不在允许集合中。")
    if sample.expected_category != actual_category:
        _failure(
            failures,
            "classification",
            f"预期 category={sample.expected_category}，实际为 {actual_category}。",
        )
    if result.get("priority") not in VALID_PRIORITIES:
        _failure(failures, "classification", "priority 不在允许集合中。")

    entered_clarification = "build_clarification" in visited_nodes
    entered_response = (
        "response_subgraph" in visited_nodes
        or "retrieve_policy_stub" in visited_nodes
    )
    event_names = [event.event for event in events]
    if sample.expected_clarification is not None:
        expected_clarification = sample.expected_clarification
        if entered_clarification != expected_clarification:
            _failure(
                failures,
                "clarification",
                (
                    "预期进入澄清分支。"
                    if expected_clarification
                    else "预期进入 response_subgraph。"
                ),
            )
        if expected_clarification and entered_response:
            _failure(failures, "clarification", "澄清工单进入了 response_subgraph。")
    elif entered_clarification and entered_response:
        _failure(
            failures,
            "clarification",
            "压力样例同时进入了澄清分支和 response_subgraph。",
        )
    elif not entered_clarification and not entered_response:
        _failure(
            failures,
            "clarification",
            "压力样例没有进入澄清分支或 response_subgraph。",
        )

    if entered_clarification and "text" not in event_names:
        _failure(failures, "clarification", "澄清分支没有输出 text 事件。")

    should_check_response = (
        sample.expected_clarification is False
        or sample.expected_clarification is None and entered_response
    )
    if should_check_response:
        if not entered_response:
            _failure(failures, "clarification", "完整工单没有进入 response_subgraph。")
        if "retrieval" not in event_names:
            _failure(failures, "evidence", "完整工单没有输出 retrieval 事件。")
        evidence_refs = result.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            _failure(failures, "evidence", "完整工单没有政策证据。")
        draft = result.get("draft_response")
        source_ids = _source_ids(evidence_refs)
        if not isinstance(draft, str) or not draft:
            _failure(failures, "evidence", "完整工单没有回复草稿。")
        elif source_ids and not any(source_id in draft for source_id in source_ids):
            _failure(failures, "evidence", "回复草稿没有引用政策 source_id。")
        if "text" not in event_names:
            _failure(failures, "evidence", "完整工单没有输出 text 事件。")

    if sample.expected_risk_level is not None:
        if result.get("risk_level") != sample.expected_risk_level:
            _failure(
                failures,
                "risk",
                (
                    f"预期 risk_level={sample.expected_risk_level}，"
                    f"实际为 {result.get('risk_level')}。"
                ),
            )
        if result.get("requires_approval") != sample.expected_requires_approval:
            _failure(failures, "risk", "requires_approval 与预期不一致。")
        if sample.expected_requires_approval and "approval_required" not in event_names:
            _failure(failures, "risk", "高风险工单没有输出 approval_required 事件。")

    if not events:
        _failure(failures, "protocol", "没有收到任何应用事件。")
    else:
        sequences = [event.sequence for event in events]
        if sequences != list(range(len(events))):
            _failure(failures, "protocol", "事件 sequence 不连续。")
        if any(event.run_id != result.get("run_id") for event in events):
            _failure(failures, "protocol", "事件 run_id 与工单 run_id 不一致。")
        if events[-1].event != "done" or event_names.count("done") != 1:
            _failure(failures, "protocol", "最后一条事件不是唯一的 done。")
        if events[-1].data.get("status") != "completed":
            _failure(failures, "protocol", "工单最终事件不是 completed。")
        serialized = json.dumps(
            [event.model_dump(mode="json") for event in events],
            ensure_ascii=False,
        )
        if any(node_name in serialized for node_name in KNOWN_NODE_NAMES):
            _failure(failures, "protocol", "公开事件泄露了内部 node 名。")

    return failures


async def _run_case(
    graph: Any,
    sample: TicketSample,
    *,
    index: int,
) -> dict[str, Any]:
    state = dict(initial_state_for_sample(sample, index=index))
    state["run_id"] = f"w14-session-05-{index + 1:02d}"
    result: dict[str, Any] = dict(state)
    visited_nodes: list[str] = []

    async def source():
        async for raw_event in graph.astream_events(state, version="v2"):
            if not isinstance(raw_event, Mapping):
                continue
            event_name = raw_event.get("event")
            node_name = raw_event.get("name")
            if (
                event_name == "on_chain_start"
                and isinstance(node_name, str)
                and node_name in KNOWN_NODE_NAMES
            ):
                visited_nodes.append(node_name)
            result.update(_chain_output(raw_event))
            yield raw_event

    adapter = GraphEventAdapter()
    events = [
        event
        async for event in adapter.adapt(source(), run_id=state["run_id"])
    ]
    failures = evaluate_case(sample, result, visited_nodes, events)
    return {
        "sample_id": sample.sample_id,
        "expected_category": sample.expected_category,
        "actual_category": result.get("category"),
        "expected_clarification": sample.expected_clarification,
        "visited_nodes": visited_nodes,
        "event_names": [event.event for event in events],
        "status": result.get("status"),
        "risk_level": result.get("risk_level"),
        "requires_approval": result.get("requires_approval"),
        "failures": failures,
    }


async def _run_acceptance(
    graph: Any,
    samples: tuple[TicketSample, ...],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        try:
            results.append(await _run_case(graph, sample, index=index))
        except Exception as exc:  # noqa: BLE001 - report one failed fixture and continue.
            results.append(
                {
                    "sample_id": sample.sample_id,
                    "expected_category": sample.expected_category,
                    "actual_category": None,
                    "failures": [
                        {
                            "category": "protocol",
                            "message": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                }
            )

    failure_counts = Counter(
        failure["category"]
        for result in results
        for failure in result.get("failures", [])
    )
    return {
        "sample_count": len(results),
        "all_assertions_passed": all(not result.get("failures") for result in results),
        "failure_counts": {
            category: failure_counts.get(category, 0)
            for category in FAILURE_CATEGORIES
        },
        "results": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the W14 Session 5 ticket acceptance fixtures."
    )
    parser.add_argument(
        "--sample",
        choices=[sample.sample_id for sample in SESSION_05_SAMPLES],
        help="Run one fixture instead of all twelve.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    samples = (
        tuple(sample for sample in SESSION_05_SAMPLES if sample.sample_id == args.sample)
        if args.sample
        else SESSION_05_SAMPLES
    )
    model = create_chat_model(AgentSettings())
    graph = create_ticket_graph(model)
    payload = asyncio.run(_run_acceptance(graph, samples))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["all_assertions_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
