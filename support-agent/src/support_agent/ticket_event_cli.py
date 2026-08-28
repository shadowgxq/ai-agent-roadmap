"""CLI for the W14 application-level ticket event stream."""

import argparse
import asyncio
import json

from support_agent.config import AgentSettings
from support_agent.graphs import create_ticket_graph
from support_agent.services import GraphEventAdapter, create_chat_model
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stream stable W14 application events for one ticket."
    )
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument(
        "--sample",
        choices=[sample.sample_id for sample in ALL_FIXED_SAMPLES],
        default="query-billing",
        help="Run one fixed ticket sample.",
    )
    selector.add_argument("--subject", help="Subject for a custom ticket.")
    parser.add_argument(
        "--description",
        help="Description for a custom ticket; use with --subject.",
    )
    parser.add_argument("--customer-tier", default="standard")
    return parser


async def _print_events(graph: object, state: dict[str, object]) -> None:
    adapter = GraphEventAdapter()
    async for event in adapter.stream(graph, state):
        print(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if (args.subject is None) != (args.description is None):
        parser.error("自定义输入必须同时提供 --subject 和 --description。")

    sample = (
        _sample_by_id(args.sample)
        if args.subject is None
        else custom_ticket_sample(
            subject=args.subject,
            description=args.description,
            customer_tier=args.customer_tier,
        )
    )
    state = dict(initial_state_for_sample(sample, index=0))
    state["run_id"] = "w14-session-04-01"

    model = create_chat_model(AgentSettings())
    graph = create_ticket_graph(model)
    asyncio.run(_print_events(graph, state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
