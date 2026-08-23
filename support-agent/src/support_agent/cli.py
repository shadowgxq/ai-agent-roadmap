"""Small command-line entry point for the Session 02 model invoke."""

import argparse

from support_agent.config import AgentSettings
from support_agent.services import create_chat_model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Invoke the support-agent model once.")
    parser.add_argument(
        "prompt", help="Prompt sent to the configured chat model")
    args = parser.parse_args()

    settings = AgentSettings()
    response = create_chat_model(settings).invoke(args.prompt)
    print(response.content)
