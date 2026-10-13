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
from .telemetry import create_telemetry


async def run_graph(store, settings, run: dict, ticket: dict):
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    model_settings = AgentSettings(database_url=settings.database_url)
    telemetry = create_telemetry(settings, run, model_settings.model if hasattr(model_settings, "model") else "test-double")
    embedding_model = os.environ["SUPPORT_AGENT_EMBEDDING_MODEL"]
    embedder = create_embedder(model=embedding_model, api_key=model_settings.api_key.get_secret_value(),
                               base_url=model_settings.resolved_base_url)
    base_retriever = HybridRetriever(settings.database_url, embedder.aembed_query, embedding_model=embedding_model)
    class ObservedRetriever:
        async def retrieve(self, *args, **kwargs):
            with telemetry.observe("retrieval", "retriever") as span:
                result = await base_retriever.retrieve(*args, **kwargs)
                if span is not None:
                    span.update(output={"evidence_count": len(result.fused), "fallback": result.fallback})
                return result
    retriever = ObservedRetriever()
    async def controlled_crm(**request):
        with telemetry.observe("crm_update", "tool"):
            async with store.tool_guard(run, request) as connection:
                result = await MockCrmRepository(settings.database_url).update_ticket(**request, connection=connection)
                await store.tool_audit(connection, run, request, result.model_dump())
                return result

    config = {"configurable": {"thread_id": str(run["thread_id"])}, "callbacks": [telemetry]}
    # LangSmith auto-tracing remains disabled; only the scalar-only Langfuse adapter is installed.
    with tracing_context(enabled=False), telemetry.observe("support-run"):
        async with create_checkpointer(settings.database_url) as checkpointer:
            graph = create_ticket_graph(create_chat_model(model_settings), checkpointer=checkpointer,
                retriever=retriever, organization_id=run["organization_id"],
                knowledge_base_id=ticket["knowledge_base_id"], tool_executor=controlled_crm)
            snapshot = await graph.aget_state(config)
            if snapshot.values:
                awaiting = any(task.interrupts for task in snapshot.tasks)
                if awaiting and run["resume_payload"]:
                    with telemetry.observe("approval") as span:
                        if span is not None:
                            span.update(output={"decision": run["resume_payload"]["decision"]})
                    graph_input = Command(resume=run["resume_payload"])
                else:
                    graph_input = None
            else:
                graph_input = {"organization_id": run["organization_id"], "user_id": run["user_id"],
                    "ticket_id": str(run["ticket_id"]), "run_id": str(run["run_id"]), "thread_id": str(run["thread_id"]),
                    "subject": ticket["subject"], "description": ticket["description"], "customer_tier": "standard", "status": "pending"}
            async for update in graph.astream(graph_input, config, stream_mode="updates"):
                for values in update.values():
                    if isinstance(values, dict):
                        await store.progress(run, values)
            snapshot = await graph.aget_state(config)
            projection = public_projection(dict(snapshot.values)) | {"trace_id": telemetry.trace_id, "metrics": telemetry.metrics(), "graph_status": snapshot.values.get("status")}
            if any(task.interrupts for task in snapshot.tasks):
                telemetry.score("waiting_approval")
                return "waiting_approval", projection
            status = "failed" if snapshot.values.get("status") == "failed" else "succeeded"
            telemetry.score(status)
            return status, projection
