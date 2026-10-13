"""Actual LangGraph pause/resume with in-memory checkpoints and explicit model/CRM doubles."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
import pytest

from support_agent.application import runtime
from support_agent.knowledge.models import EvidenceRef
from support_agent.knowledge.retrieval import RetrievalResult
from support_agent.models import CrmUpdateResult, RiskAssessment, TicketWorkflowClassification
from test_ticket_workflow import StubModel


@pytest.mark.parametrize("decision", ["approve", "reject", "revise"])
def test_graph_approval_resume_and_checkpoint_replay_do_not_repeat_crm(monkeypatch, decision):
    async def scenario():
        checkpoints = InMemorySaver()
        writes = {}
        audits = []
        @asynccontextmanager
        async def checkpointer(url):
            yield checkpoints
        class Retriever:
            async def retrieve(self, org, kb, query):
                return RetrievalResult(query, org, kb, fused=[EvidenceRef(
                    chunk_id="billing_refund_001", document_id="refund", document_title="Refund policy",
                    document_version=1, snippet="退款需要核对订单，执行前需要审批。", score=1)])
        class Crm:
            def __init__(self, url):
                pass
            async def update_ticket(self, connection=None, **request):
                key = request["idempotency_key"]
                replayed = key in writes
                writes.setdefault(key, request)
                return CrmUpdateResult(organization_id=request["organization_id"], ticket_id=request["ticket_id"],
                    status="resolved", update_count=1, idempotency_key=key, replayed=replayed)
        class Store:
            def __init__(self):
                self.projection = {}
                self.approved = False
            async def progress(self, run, values):
                self.projection.update(runtime.public_projection(values))
            @asynccontextmanager
            async def tool_guard(self, run, request):
                assert self.approved
                yield object()
            async def tool_audit(self, conn, run, request, result):
                audits.append(request["idempotency_key"])
        model = StubModel(TicketWorkflowClassification(category="billing", priority="high",
            needs_clarification=False, missing_fields=[], reason="complete refund request"),
            risk_assessment=RiskAssessment(risk_level="high", risk_reasons=["CRM update"], requires_approval=True))
        monkeypatch.setattr(runtime, "load_dotenv", lambda *args, **kwargs: None)
        monkeypatch.setenv("SUPPORT_AGENT_EMBEDDING_MODEL", "offline-model-double")
        monkeypatch.setattr(runtime, "AgentSettings", lambda **kwargs: SimpleNamespace(api_key=SecretStr("unused"), resolved_base_url=None))
        monkeypatch.setattr(runtime, "create_chat_model", lambda settings: model)
        monkeypatch.setattr(runtime, "create_embedder", lambda **kwargs: SimpleNamespace(aembed_query=None))
        monkeypatch.setattr(runtime, "HybridRetriever", lambda *args, **kwargs: Retriever())
        monkeypatch.setattr(runtime, "create_checkpointer", checkpointer)
        monkeypatch.setattr(runtime, "MockCrmRepository", Crm)
        store = Store()
        settings = SimpleNamespace(database_url="unused")
        run = {"organization_id": "org-a", "user_id": "u", "ticket_id": str(uuid4()),
               "run_id": str(uuid4()), "thread_id": str(uuid4()), "resume_payload": None}
        ticket = {"knowledge_base_id": "kb", "subject": "申请退款", "description": "订单order123需要退款，原因是重复购买。"}
        status, projection = await runtime.run_graph(store, settings, run, ticket)
        assert status == "waiting_approval" and writes == {}
        store.approved = decision == "approve"
        original_hash = projection["proposal_hash"]
        run["resume_payload"] = {"actor_id": "approver", "decision": decision, "feedback": None if decision == "approve" else "请重新审查",
                                 "proposal_hash": projection["proposal_hash"]}
        status, projection = await runtime.run_graph(store, settings, run, ticket)
        if decision == "revise":
            assert status == "waiting_approval" and writes == {}
            assert projection["proposal_hash"] != original_hash
            store.approved = True
            run["resume_payload"] = {"actor_id": "approver", "decision": "approve", "feedback": None, "proposal_hash": projection["proposal_hash"]}
            status, projection = await runtime.run_graph(store, settings, run, ticket)
        expected_writes = 0 if decision == "reject" else 1
        assert status == "succeeded" and len(writes) == len(audits) == expected_writes
        if expected_writes:
            assert projection["tool_result"]["update_count"] == 1
        # A crash after checkpoint completion but before the run projection is saved
        # reopens the same checkpoint; an already consumed approval is not resumed again.
        status, projection = await runtime.run_graph(store, settings, run, ticket)
        assert status == "succeeded" and len(writes) == len(audits) == expected_writes
    asyncio.run(scenario())
