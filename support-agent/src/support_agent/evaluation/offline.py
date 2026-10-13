"""Execute the real ticket Graph with explicit local model/retrieval/CRM doubles."""

import json
import re
import time

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from support_agent.graphs import create_ticket_graph
from support_agent.knowledge.models import EvidenceRef
from support_agent.knowledge.retrieval import RetrievalResult, search_terms
from support_agent.models import CrmUpdateResult, RiskAssessment, TicketWorkflowClassification
from support_agent.application.security import public_projection, validate_crm_request
from .catalog import E2ECase, isolated_ids


class ScriptedModel:
    """Keyword fixture behavior, independent of expected-case assertions."""
    def __init__(self, timeout=False, max_calls=8):
        self.timeout = timeout
        self.calls = 0
        self.max_calls = max_calls

    def count(self):
        self.calls += 1
        if self.calls > self.max_calls:
            raise RuntimeError("Offline model-call budget exhausted")

    def with_structured_output(self, schema, **kwargs):
        parent = self
        class Structured:
            def invoke(self, messages):
                parent.count()
                text = messages[-1].content.lower()
                if parent.timeout:
                    raise TimeoutError("Simulated provider timeout")
                if schema is RiskAssessment:
                    high = "please refund" in text
                    return RiskAssessment(risk_level="high" if high else "low", requires_approval=high,
                                          risk_reasons=["External write requested"] if high else [])
                if schema is not TicketWorkflowClassification:
                    raise ValueError("Unexpected structured schema")
                category = "other"
                for label, words in [("billing", ["refund", "charge", "invoice", "subscription"]),
                                     ("account", ["email", "account", "login", "identity"]),
                                     ("technical", ["api", "endpoint", "service outage"]),
                                     ("product", ["project", "export", "csv", "retention"])]:
                    if any(word in text for word in words):
                        category = label
                        break
                missing = []
                if "please refund" in text:
                    missing = [field for field in ("order_id", "refund_reason")
                               if ("order_id=" if field == "order_id" else "reason=") not in text]
                elif "i need help" in text:
                    missing = ["request_context"]
                return TicketWorkflowClassification(category=category, priority="normal",
                    needs_clarification=bool(missing), missing_fields=missing, reason="Offline keyword fixture")
        return Structured()

    def invoke(self, messages):
        self.count()
        match = re.search(r"政策证据（只允许使用这些内容）：\n(.+?)\n\n可用引用 ID", messages[-1].content, re.S)
        refs = json.loads(match[1]) if match else []
        return AIMessage(content="\n".join(f"{ref['snippet']} [{ref['source_id']}]" for ref in refs))


class ScopedFixtureRetriever:
    def __init__(self, corpus: list[dict], organization_id: str, top_k=5):
        self.corpus, self.organization_id, self.top_k = corpus, organization_id, top_k

    async def retrieve(self, organization_id, knowledge_base_id, query):
        if organization_id != self.organization_id or knowledge_base_id != "policy":
            raise PermissionError("Fixture tenant/KB mismatch")
        terms = set(search_terms(query))
        scored = []
        for document in self.corpus:
            # W19 corpus organization B is intentionally inaccessible in this fixture.
            if document["organization_id"] != "eval-org-a":
                continue
            score = len(terms & set(search_terms(document["text"])))
            if score:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1]["document_id"]))
        refs = [EvidenceRef(chunk_id="fixture-" + doc["document_id"], document_id=doc["document_id"],
            document_title=doc["title"], document_version=1, heading_path=[doc["title"]],
            snippet=doc["text"], score=float(score)) for score, doc in scored[:self.top_k]]
        return RetrievalResult(query, organization_id, knowledge_base_id, fused=refs)


async def execute_offline(case: E2ECase, manifest: dict, corpus: list[dict], batch_id: str,
                          *, top_k: int = 5) -> dict:
    start = time.monotonic()
    ids = isolated_ids(case, batch_id)
    state = ids | {"subject": case.subject, "description": case.description, "customer_tier": "standard", "status": "pending"}
    checkpoint = InMemorySaver()
    model = ScriptedModel(case.scenario == "timeout", manifest["budget"]["max_model_calls"])
    writes, audit, events = {}, [], []
    authorized = False
    approval_count = 0
    unauthorized_writes = 0
    def append(kind, payload):
        events.append({"sequence": len(events) + 1, "kind": kind, "payload": payload})
    async def crm(**request):
        nonlocal unauthorized_writes
        validate_crm_request(ids, request)
        if not authorized:
            unauthorized_writes += 1
            raise PermissionError("Approval required")
        key = request["idempotency_key"]
        replayed = key in writes
        if not replayed:
            if len(writes) >= manifest["budget"]["max_tool_calls"]:
                raise RuntimeError("Tool budget exhausted")
            writes[key] = request
            audit.append({"action": "crm_update", "idempotency_key": key})
        return CrmUpdateResult(organization_id=ids["organization_id"], ticket_id=ids["ticket_id"],
                              status="resolved", update_count=1, idempotency_key=key, replayed=replayed)
    graph = create_ticket_graph(model, checkpointer=checkpoint,
        retriever=ScopedFixtureRetriever(corpus, ids["organization_id"], top_k),
        organization_id=ids["organization_id"], knowledge_base_id="policy", tool_executor=crm,
        interrupt_before=["response_subgraph"] if case.scenario == "cancel" else None)
    config = {"configurable": {"thread_id": ids["thread_id"]}}
    append("status", {"status": "queued"})
    append("status", {"status": "running"})
    error_code = None
    try:
        async def consume(graph_input):
            async for update in graph.astream(graph_input, config, stream_mode="updates"):
                for node, values in update.items():
                    if isinstance(values, dict):
                        append("node", {"node": node, **public_projection(values)})
        await consume(state)
        snapshot = await graph.aget_state(config)
        initial_approval = any(task.interrupts for task in snapshot.tasks)
        if case.scenario == "cancel":
            result = dict(snapshot.values) | {"status": "cancelled"}
        else:
            for decision in case.decisions:
                if not any(task.interrupts for task in snapshot.tasks):
                    raise ValueError("Fixture decision has no awaiting proposal")
                approval_count += 1
                authorized = decision == "approve"
                audit.append({"action": "approval", "decision": decision, "proposal_hash": snapshot.values["proposal_hash"]})
                await consume(Command(resume={"decision": decision, "actor_id": "eval-approver",
                    "proposal_hash": snapshot.values["proposal_hash"], "feedback": None if decision == "approve" else "请重新核对政策"}))
                snapshot = await graph.aget_state(config)
            if case.scenario == "replay":
                await consume(None)
                snapshot = await graph.aget_state(config)
            result = dict(snapshot.values)
        waiting = any(task.interrupts for task in snapshot.tasks) and case.scenario != "cancel"
        status = "waiting_approval" if waiting else "cancelled" if case.scenario == "cancel" else "failed" if result.get("status") == "failed" else "succeeded"
    except Exception as exc:
        snapshot = await graph.aget_state(config)
        result = dict(snapshot.values) | {"status": "failed"}
        status, error_code, initial_approval = "failed", type(exc).__name__, False
    append("status" if status == "waiting_approval" else "done", {"status": status})
    refs = result.get("evidence_refs", [])
    return {"case_id": case.id, "source": "offline", "scope": "real-graph-with-local-test-doubles",
            **ids, "graph_status": result.get("status"), "status": status, "category": result.get("category"),
            "answer": result.get("draft_response", ""), "evidence": [ref.model_dump() if hasattr(ref, "model_dump") else ref for ref in refs],
            "approval_required": initial_approval, "approval_count": approval_count,
            "writes": len(writes), "unauthorized_writes": unauthorized_writes, "audit": audit, "events": events,
            "model_calls": model.calls, "cost_usd": None, "input_tokens": None, "output_tokens": None,
            "latency_seconds": time.monotonic() - start, "error_code": error_code}
