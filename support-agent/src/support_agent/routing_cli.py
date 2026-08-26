"""Command-line entry point for the LangGraph routing workflow."""

import argparse
import json

from support_agent.config import AgentSettings
from support_agent.graphs import create_routing_graph
from support_agent.services import create_chat_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Route a coding task through a LangGraph workflow.")
    parser.add_argument("task", help="Coding task to classify and process")
    args = parser.parse_args()

    settings = AgentSettings()
    model = create_chat_model(settings)
    graph = create_routing_graph(model)
    result = graph.invoke({"task": args.task, "status": "pending"})

    print(json.dumps(result, ensure_ascii=False, indent=2))
