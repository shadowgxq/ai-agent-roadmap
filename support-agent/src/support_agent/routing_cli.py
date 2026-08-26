"""Command-line entry point for the LangGraph routing workflow."""

import argparse
import json
import sys

from support_agent.config import AgentSettings
from support_agent.graphs import create_routing_graph
from support_agent.services import create_chat_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Route a coding task through a LangGraph workflow.")
    parser.add_argument("task", help="Coding task to classify and process")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Print node updates to stderr while the graph runs",
    )
    args = parser.parse_args()

    settings = AgentSettings()
    model = create_chat_model(settings)
    graph = create_routing_graph(model)
    initial_state = {"task": args.task, "status": "pending"}

    if args.trace:
        result = dict(initial_state)
        for update in graph.stream(initial_state, stream_mode="updates"):
            for node, node_update in update.items():
                result.update(node_update)
                trace = {"node": node, "updates": node_update}
                print(
                    f"[trace] {json.dumps(trace, ensure_ascii=False)}",
                    file=sys.stderr,
                )
    else:
        result = graph.invoke(initial_state)

    print(json.dumps(result, ensure_ascii=False, indent=2))
