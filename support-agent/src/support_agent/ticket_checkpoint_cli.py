"""Offline W15 CLI for creating and reading PostgreSQL checkpoints."""
import argparse
import asyncio
import json
from uuid import uuid4

from support_agent.config import AgentSettings
from support_agent.graphs import create_ticket_graph
from support_agent.models import TicketAgentState
from support_agent.persistence import create_checkpointer
from support_agent.services import get_run_snapshot, start_run


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


def _snapshot_payload(snapshot: object, *, thread_id: str) -> dict[str, object]:
    values = dict(getattr(snapshot, "values", {}) or {})
    return {
        "found": bool(values),
        "thread_id": thread_id,
        "ticket_id": values.get("ticket_id"),
        "run_id": values.get("run_id"),
        "status": values.get("status"),
        "next": list(getattr(snapshot, "next", ()) or ()),
        "draft_response": values.get("draft_response"),
    }


async def _start(settings: AgentSettings, thread_id: str) -> dict[str, object]:
    async with create_checkpointer(settings.database_url) as checkpointer:
        graph = create_ticket_graph(checkpointer=checkpointer)
        state = build_demo_state(thread_id)
        await start_run(graph, state)
        snapshot = await get_run_snapshot(graph, thread_id=thread_id)
        return _snapshot_payload(snapshot, thread_id=thread_id)


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
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    settings = AgentSettings()

    if args.command == "start":
        thread_id = args.thread_id or str(uuid4())
        payload = asyncio.run(_start(settings, thread_id))
    else:
        payload = asyncio.run(_inspect(settings, args.thread_id))

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["found"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
