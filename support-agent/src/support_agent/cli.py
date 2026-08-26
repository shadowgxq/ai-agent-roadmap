"""Command-line entry point for the ticket support agent."""

import argparse

from support_agent.config import AgentSettings
from support_agent.graphs import create_support_agent
from support_agent.services import create_chat_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify a support ticket with the LangChain agent.")
    parser.add_argument(
        "ticket", help="Customer support ticket to classify")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Print model, tool-call, and tool-result messages",
    )
    args = parser.parse_args()

    settings = AgentSettings()
    model = create_chat_model(settings)
    agent = create_support_agent(model)
    result = agent.invoke({
        "messages": [{"role": "user", "content": args.ticket}],
    })

    if args.trace:
        for message in result["messages"]:
            message.pretty_print()

    classification = result["structured_response"]
    print(classification.model_dump_json(indent=2))
