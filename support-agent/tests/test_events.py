import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage

from support_agent.services import GraphEventAdapter


FIXED_TIME = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _raw_event(
    event: str,
    name: str,
    *,
    output: Any = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {}
    if output is not None:
        data["output"] = output
    result: dict[str, object] = {
        "event": event,
        "name": name,
        "data": data,
    }
    if metadata is not None:
        result["metadata"] = metadata
    return result


def _collect(raw_events: list[dict[str, object]]) -> list[Any]:
    async def source():
        for raw_event in raw_events:
            yield raw_event

    async def run() -> list[Any]:
        adapter = GraphEventAdapter(clock=lambda: FIXED_TIME)
        return [
            event
            async for event in adapter.adapt(source(), run_id="run_events_1")
        ]

    return asyncio.run(run())


def test_adapter_emits_allowlisted_ordered_events_and_done_last() -> None:
    events = _collect(
        [
            _raw_event("on_chain_start", "secret_node"),
            _raw_event("on_chain_start", "normalize_ticket"),
            _raw_event(
                "on_chain_end",
                "normalize_ticket",
                output={"status": "normalized"},
            ),
            _raw_event("on_chain_start", "retrieve_policy_stub"),
            _raw_event(
                "on_chain_end",
                "retrieve_policy_stub",
                output={
                    "status": "retrieving",
                    "evidence_refs": [
                        {
                            "source_id": "billing_refund_001",
                            "title": "账单政策",
                            "snippet": "需要核对订单号。",
                        }
                    ],
                },
            ),
            _raw_event(
                "on_chat_model_end",
                "ChatOpenAI",
                output=AIMessage(
                    content="draft",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 4,
                        "total_tokens": 14,
                    },
                ),
                metadata={"langgraph_node": "draft_response"},
            ),
            _raw_event(
                "on_chain_end",
                "draft_response",
                output={
                    "status": "drafted",
                    "draft_response": "依据 [billing_refund_001] 回复。",
                },
            ),
            _raw_event(
                "on_chain_end",
                "assess_risk",
                output={
                    "status": "assessed",
                    "risk_level": "high",
                    "risk_reasons": ["需要人工审批"],
                    "requires_approval": True,
                },
            ),
            _raw_event(
                "on_chain_end",
                "finalize",
                output={"status": "completed"},
            ),
        ]
    )

    assert [event.sequence for event in events] == list(range(len(events)))
    assert all(event.run_id == "run_events_1" for event in events)
    assert events[-1].event == "done"
    assert events[-1].data == {"status": "completed"}
    assert "retrieval" in [event.event for event in events]
    assert "text" in [event.event for event in events]
    assert "context_usage" in [event.event for event in events]
    assert "approval_required" in [event.event for event in events]

    serialized = json.dumps(
        [event.model_dump(mode="json") for event in events],
        ensure_ascii=False,
    )
    assert "secret_node" not in serialized
    assert "normalize_ticket" not in serialized


def test_clarification_path_skips_response_events() -> None:
    events = _collect(
        [
            _raw_event("on_chain_start", "build_clarification"),
            _raw_event(
                "on_chain_end",
                "build_clarification",
                output={
                    "status": "needs_clarification",
                    "draft_response": "请提供订单号。",
                },
            ),
            _raw_event(
                "on_chain_end",
                "finalize",
                output={"status": "completed"},
            ),
        ]
    )

    event_names = [event.event for event in events]
    assert "text" in event_names
    assert "retrieval" not in event_names
    assert "approval_required" not in event_names
    assert events[-1].event == "done"


def test_failed_graph_becomes_failed_done_event() -> None:
    events = _collect(
        [
            _raw_event(
                "on_chain_end",
                "draft_response",
                output={
                    "status": "failed",
                    "error_code": "DRAFT_GENERATION_FAILED",
                    "error_message": "没有引用政策证据。",
                },
            ),
            _raw_event(
                "on_chain_end",
                "finalize",
                output={"status": "failed"},
            ),
        ]
    )

    assert events[-1].event == "done"
    assert events[-1].data == {
        "status": "failed",
        "error_code": "DRAFT_GENERATION_FAILED",
        "error_message": "没有引用政策证据。",
    }
