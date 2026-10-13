"""Reuse W15 durable Graph/CRM and W19 evidence under the W20 host policy."""

import os
from dotenv import load_dotenv
from langgraph.types import Command
from langsmith import tracing_context

from support_agent.config import AgentSettings
from support_agent.config.settings import PROJECT_ROOT
from support_agent.graphs import create_ticket_graph
from support_agent.knowledge.embeddings import create_embedder
from support_agent.knowledge.retrieval import HybridRetriever
from support_agent.persistence import create_checkpointer, MockCrmRepository
from support_agent.services import create_chat_model
from .security import public_projection


async def run_graph(store, settings, run: dict, ticket: dict):
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    model_settings = AgentSettings(database_url=settings.database_url)
    embedding_model = os.environ["SUPPORT_AGENT_EMBEDDING_MODEL"]
    embedder = create_embedder(model=embedding_model, api_key=model_settings.api_key.get_secret_value(),
                               base_url=model_settings.resolved_base_url)
    retriever = HybridRetriever(settings.database_url, embedder.aembed_query, embedding_model=embedding_model)
    async def controlled_crm(**request):
        async with store.tool_guard(run, request) as connection:
            result = await MockCrmRepository(settings.database_url).update_ticket(**request, connection=connection)
            await store.tool_audit(connection, run, request, result.model_dump())
            return result

    config = {"configurable": {"thread_id": str(run["thread_id"])}, "callbacks": []}
    # W21 enables tracing only after a redacting callback has been installed.
    with tracing_context(enabled=False):
        async with create_checkpointer(settings.database_url) as checkpointer:
            graph = create_ticket_graph(create_chat_model(model_settings), checkpointer=checkpointer,
                retriever=retriever, organization_id=run["organization_id"],
                knowledge_base_id=ticket["knowledge_base_id"], tool_executor=controlled_crm)
            snapshot = await graph.aget_state(config)
            if snapshot.values:
                awaiting = any(task.interrupts for task in snapshot.tasks)
                graph_input = Command(resume=run["resume_payload"]) if awaiting and run["resume_payload"] else None
            else:
                graph_input = {"organization_id": run["organization_id"], "user_id": run["user_id"],
                    "ticket_id": str(run["ticket_id"]), "run_id": str(run["run_id"]), "thread_id": str(run["thread_id"]),
                    "subject": ticket["subject"], "description": ticket["description"], "customer_tier": "standard", "status": "pending"}
            async for update in graph.astream(graph_input, config, stream_mode="updates"):
                for values in update.values():
                    if isinstance(values, dict):
                        await store.progress(run, values)
            snapshot = await graph.aget_state(config)
            projection = public_projection(dict(snapshot.values))
            if any(task.interrupts for task in snapshot.tasks):
                return "waiting_approval", projection
            return ("failed" if snapshot.values.get("status") == "failed" else "succeeded"), projection
