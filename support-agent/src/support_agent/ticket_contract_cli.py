"""Offline CLI for inspecting the W14 ticket state and graph contract."""

import json

from support_agent.graphs import (
    NODE_IO_CONTRACTS,
    build_clarification,
    create_ticket_graph,
    finalize_ticket,
    normalize_ticket,
)
from support_agent.models import TicketAgentState


def build_demo_state() -> TicketAgentState:
    """Return a hand-written incomplete ticket for the deterministic path."""

    return {
        "organization_id": "org_demo",
        "user_id": "user_demo",
        "ticket_id": "ticket_demo",
        "run_id": "run_demo",
        "thread_id": "thread_demo",
        "subject": "无法退款",
        "description": "点击退款后一直失败。",
        "customer_tier": "enterprise",
        "status": "pending",
    }


def main() -> None:
    graph = create_ticket_graph()
    state = build_demo_state()
    state.update(normalize_ticket(state))
    state.update({
        "category": "billing",
        "priority": "high",
        "missing_fields": ["order_id", "refund_reason"],
        "status": "classified",
    })
    state.update(build_clarification(state))
    state.update(finalize_ticket(state))

    graph_view = graph.get_graph()
    output = {
        "graph_nodes": sorted(graph_view.nodes),
        "graph_edges": len(graph_view.edges),
        "node_contracts": {
            name: {
                "reads": contract.reads,
                "writes": contract.writes,
                "calls_model": contract.calls_model,
                "error_codes": contract.error_codes,
            }
            for name, contract in NODE_IO_CONTRACTS.items()
        },
        "deterministic_demo": state,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
