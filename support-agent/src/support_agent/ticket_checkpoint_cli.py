"""Offline W15 CLI for checkpoint and human-approval experiments."""

import argparse
import asyncio
from collections.abc import Mapping
import json
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from support_agent.config import AgentSettings
from support_agent.graphs import create_ticket_graph
from support_agent.models import ApprovalDecision, TicketAgentState
from support_agent.persistence import (
    ApprovalRepository,
    ToolActionRepository,
    create_checkpointer,
    initialize_business_schema,
)
from support_agent.services import (
    build_idempotency_key,
    get_run_snapshot,
    resume_run,
    start_run,
)


def build_demo_state(thread_id: str) -> TicketAgentState:
    """Build a clarification-path sample that never invokes an LLM."""

    return {
        "organization_id": "org_w15_demo",
        "user_id": "user_w15_demo",
        "ticket_id": f"ticket_{uuid4()}",
        "run_id": f"run_{uuid4()}",
        "thread_id": thread_id,
        "subject": "申请退款",
        "description": "我想申请退款，但还没有提供订单号和退款原因。",
        "customer_tier": "standard",
        "status": "pending",
        "category": "billing",
        "priority": "normal",
        "missing_fields": ["order_id", "refund_reason"],
    }


def build_approval_demo_state(thread_id: str) -> TicketAgentState:
    """Build a complete high-risk sample for the offline approval graph."""

    return {
        "organization_id": "org_w15_demo",
        "user_id": "user_w15_demo",
        "ticket_id": f"ticket_{uuid4()}",
        "run_id": f"run_{uuid4()}",
        "thread_id": thread_id,
        "subject": "请直接帮我完成退款",
        "description": "订单 order_demo_001 信息完整，请直接执行退款。",
        "customer_tier": "standard",
        "status": "pending",
        "category": "billing",
        "priority": "high",
        "missing_fields": [],
        "revision_count": 0,
    }


def _offline_approval_response(state: TicketAgentState) -> dict[str, object]:
    """Create a deterministic high-risk proposal without calling an LLM."""

    revision_count = state.get("revision_count", 0)
    feedback = state.get("approval_feedback")
    if feedback:
        draft = (
            f"修订版 {revision_count}：我们会先核对退款条件，不承诺已经退款。"
            f"人工反馈：{feedback}"
        )
    else:
        draft = "我们准备核对订单并将 CRM 工单状态更新为 resolved。"
    return {
        "draft_response": draft,
        "risk_level": "high",
        "risk_reasons": ["该操作会修改 CRM 工单状态，需要人工审批。"],
        "requires_approval": True,
        "status": "assessed",
    }


def _create_offline_approval_subgraph():
    builder = StateGraph(TicketAgentState)
    builder.add_node("offline_approval_response", _offline_approval_response)
    builder.add_edge(START, "offline_approval_response")
    builder.add_edge("offline_approval_response", END)
    return builder.compile()


def _interrupt_payloads(
    snapshot: object,
    result: Mapping[str, object] | None,
) -> list[object]:
    raw_interrupts: list[object] = []
    if result is not None:
        result_interrupts = result.get("__interrupt__", ())
        if isinstance(result_interrupts, (list, tuple)):
            raw_interrupts.extend(result_interrupts)

    if not raw_interrupts:
        for task in getattr(snapshot, "tasks", ()) or ():
            raw_interrupts.extend(getattr(task, "interrupts", ()) or ())

    return [getattr(item, "value", item) for item in raw_interrupts]


def _snapshot_payload(
    snapshot: object,
    *,
    thread_id: str,
    result: Mapping[str, object] | None = None,
) -> dict[str, object]:
    values = dict(getattr(snapshot, "values", {}) or {})
    interrupts = _interrupt_payloads(snapshot, result)
    return {
        "found": bool(values),
        "thread_id": thread_id,
        "ticket_id": values.get("ticket_id"),
        "run_id": values.get("run_id"),
        "status": values.get("status"),
        "next": list(getattr(snapshot, "next", ()) or ()),
        "draft_response": values.get("draft_response"),
        "approval_decision": values.get("approval_decision"),
        "approval_feedback": values.get("approval_feedback"),
        "approval_error": values.get("approval_error"),
        "proposal_hash": values.get("proposal_hash"),
        "revision_count": values.get("revision_count", 0),
        "waiting_for_approval": bool(interrupts),
        "interrupts": interrupts,
    }


async def _start(settings: AgentSettings, thread_id: str) -> dict[str, object]:
    async with create_checkpointer(settings.database_url) as checkpointer:
        graph = create_ticket_graph(checkpointer=checkpointer)
        state = build_demo_state(thread_id)
        result = await start_run(graph, state)
        snapshot = await get_run_snapshot(graph, thread_id=thread_id)
        return _snapshot_payload(
            snapshot,
            thread_id=thread_id,
            result=result,
        )


async def _approval_start(
    settings: AgentSettings,
    thread_id: str,
) -> dict[str, object]:
    await initialize_business_schema(settings.database_url)
    async with create_checkpointer(settings.database_url) as checkpointer:
        graph = create_ticket_graph(
            checkpointer=checkpointer,
            response_subgraph=_create_offline_approval_subgraph(),
        )
        state = build_approval_demo_state(thread_id)
        result = await start_run(graph, state)
        snapshot = await get_run_snapshot(graph, thread_id=thread_id)
        return _snapshot_payload(
            snapshot,
            thread_id=thread_id,
            result=result,
        )


async def _resume(
    settings: AgentSettings,
    *,
    thread_id: str,
    decision: ApprovalDecision,
    actor_id: str,
    proposal_hash: str,
    feedback: str | None,
) -> dict[str, object]:
    await initialize_business_schema(settings.database_url)
    approval_repository = ApprovalRepository(settings.database_url)
    tool_action_repository = ToolActionRepository(settings.database_url)
    async with create_checkpointer(settings.database_url) as checkpointer:
        graph = create_ticket_graph(
            checkpointer=checkpointer,
            response_subgraph=_create_offline_approval_subgraph(),
        )
        result = await resume_run(
            graph,
            thread_id=thread_id,
            decision=decision,
            actor_id=actor_id,
            proposal_hash=proposal_hash,
            approval_repository=approval_repository,
            tool_action_repository=tool_action_repository,
            feedback=feedback,
        )
        snapshot = await get_run_snapshot(graph, thread_id=thread_id)
        payload = _snapshot_payload(
            snapshot,
            thread_id=thread_id,
            result=result,
        )
        values = dict(snapshot.values or {})
        run_id = values.get("run_id")
        approvals = (
            await approval_repository.list_for_run(str(run_id))
            if run_id is not None
            else []
        )
        payload["approvals"] = [
            record.model_dump(mode="json") for record in approvals
        ]

        if decision == "approve" and run_id is not None:
            action_payload = {
                "ticket_id": str(values["ticket_id"]),
                "status": "resolved",
            }
            idempotency_key = build_idempotency_key(
                organization_id=str(values["organization_id"]),
                ticket_id=str(values["ticket_id"]),
                run_id=str(run_id),
                action_type="update_crm_ticket",
                payload=action_payload,
            )
            action = await tool_action_repository.get_by_key(idempotency_key)
            payload["tool_action"] = (
                action.model_dump(mode="json") if action is not None else None
            )
        else:
            payload["tool_action"] = None
        return payload


async def _inspect(settings: AgentSettings, thread_id: str) -> dict[str, object]:
    async with create_checkpointer(settings.database_url) as checkpointer:
        graph = create_ticket_graph(checkpointer=checkpointer)
        snapshot = await get_run_snapshot(graph, thread_id=thread_id)
        return _snapshot_payload(snapshot, thread_id=thread_id)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or inspect a W15 PostgreSQL checkpoint without LLM calls."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser(
        "start",
        help="Run the deterministic clarification path and save checkpoints.",
    )
    start_parser.add_argument(
        "--thread-id",
        default=None,
        help="Stable persistence cursor; defaults to a new UUID.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Read the latest checkpoint without rerunning the graph.",
    )
    inspect_parser.add_argument("thread_id")

    approval_parser = subparsers.add_parser(
        "approval-start",
        help="Run an offline high-risk proposal until interrupt().",
    )
    approval_parser.add_argument(
        "--thread-id",
        default=None,
        help="Stable persistence cursor; defaults to a new UUID.",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume an interrupted approval thread.",
    )
    resume_parser.add_argument("thread_id")
    resume_parser.add_argument(
        "decision",
        choices=("approve", "reject", "revise"),
    )
    resume_parser.add_argument("--actor-id", required=True)
    resume_parser.add_argument("--proposal-hash", required=True)
    resume_parser.add_argument("--feedback")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings = AgentSettings()

    if args.command == "start":
        thread_id = args.thread_id or str(uuid4())
        payload = asyncio.run(_start(settings, thread_id))
    elif args.command == "inspect":
        payload = asyncio.run(_inspect(settings, args.thread_id))
    elif args.command == "approval-start":
        thread_id = args.thread_id or str(uuid4())
        payload = asyncio.run(_approval_start(settings, thread_id))
    else:
        feedback = args.feedback.strip() if args.feedback else None
        if args.decision in {"reject", "revise"} and not feedback:
            parser.error("reject 或 revise 必须通过 --feedback 提供人工意见。")
        payload = asyncio.run(
            _resume(
                settings,
                thread_id=args.thread_id,
                decision=args.decision,
                actor_id=args.actor_id,
                proposal_hash=args.proposal_hash,
                feedback=feedback,
            )
        )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["found"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
