"""W19 ticket entry point with host-supplied tenant and PostgreSQL hybrid retrieval."""

import argparse
import asyncio
import json
from uuid import uuid4

from support_agent.config import AgentSettings
from support_agent.graphs import create_ticket_graph
from support_agent.knowledge.embeddings import create_embedder
from support_agent.knowledge.retrieval import HybridRetriever
from support_agent.knowledge_cli import environment
from support_agent.persistence import create_checkpointer
from support_agent.services import create_chat_model, start_run


async def run(args: argparse.Namespace) -> dict:
    database_url, model, api_key, base_url = environment()
    embedder = create_embedder(model=model, api_key=api_key, base_url=base_url)
    retriever = HybridRetriever(database_url, embedder.aembed_query,
                                embedding_model=model, min_similarity=args.min_similarity)
    async with create_checkpointer(database_url) as checkpointer:
        graph = create_ticket_graph(create_chat_model(AgentSettings()), checkpointer=checkpointer,
                                     retriever=retriever, organization_id=args.organization,
                                     knowledge_base_id=args.kb)
        state = {"organization_id": args.organization, "user_id": "cli-user",
                 "ticket_id": str(uuid4()), "run_id": str(uuid4()), "thread_id": str(uuid4()),
                 "subject": args.subject, "description": args.description,
                 "customer_tier": "standard", "status": "pending"}
        # The CLI stops at approval. It does not authorize or perform CRM writes.
        return await start_run(graph, state)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--min-similarity", type=float, default=0.35)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2,
                     default=lambda value: value.model_dump() if hasattr(value, "model_dump") else str(value)))


if __name__ == "__main__":
    main()
