"""Opt-in collector for an already running application. Never starts services."""

import asyncio
import os
import time
from uuid import uuid4

import httpx

from support_agent.application.settings import ApplicationSettings
from support_agent.config import AgentSettings
from support_agent.knowledge.embeddings import create_embedder
from support_agent.knowledge.models import Document, KnowledgeBase
from support_agent.knowledge.parsing import chunk_sections, parse_source
from support_agent.knowledge.repository import KnowledgeRepository


async def collect_live(url: str, manifest: dict, cases, corpus, *, permit_model_calls: bool):
    if not permit_model_calls:
        raise PermissionError("Live E2E evaluation consumes provider tokens; explicitly permit model calls")
    settings = ApplicationSettings()
    model_settings = AgentSettings(database_url=settings.database_url)
    # Client credentials are separate from server-side scrypt hashes; never pass them in argv or reports.
    async with httpx.AsyncClient(base_url=url.rstrip("/"), timeout=30) as operator, httpx.AsyncClient(base_url=url.rstrip("/"), timeout=30) as approver:
        sessions = []
        for client, role in ((operator, "OPERATOR"), (approver, "APPROVER")):
            response = await client.post("/support-api/auth/login", json={
                "username": os.environ[f"SUPPORT_EVAL_{role}_USERNAME"], "password": os.environ[f"SUPPORT_EVAL_{role}_PASSWORD"]})
            response.raise_for_status()
            sessions.append(response.json())
        org = sessions[0]["identity"]["organization_id"]
        if org != sessions[1]["identity"]["organization_id"] or not org.startswith("eval-"):
            raise ValueError("Live fixtures require operator/approver accounts in the same dedicated eval- tenant")
        operator.headers["X-CSRF-Token"] = sessions[0]["csrf_token"]
        approver.headers["X-CSRF-Token"] = sessions[1]["csrf_token"]
        embedding_model = os.environ["SUPPORT_AGENT_EMBEDDING_MODEL"]
        embedder = create_embedder(model=embedding_model, api_key=model_settings.api_key.get_secret_value(), base_url=model_settings.resolved_base_url)
        repository = KnowledgeRepository(settings.database_url)
        batch = uuid4().hex
        rows = []
        for case in cases:
            # Each case gets its own KB, document versions, ticket, run, checkpoint and CRM keys.
            kb = f"w21-{batch}-{case.id}"
            await repository.create_base(KnowledgeBase(organization_id=org, knowledge_base_id=kb, name=kb,
                embedding_model=embedding_model, embedding_dimensions=int(os.getenv("SUPPORT_EVAL_EMBEDDING_DIMENSIONS", "1536"))))
            for document in corpus:
                owner = org if document["organization_id"] == "eval-org-a" else f"eval-foreign-{batch}"
                if owner != org:
                    await repository.create_base(KnowledgeBase(organization_id=owner, knowledge_base_id=kb, name=kb,
                        embedding_model=embedding_model, embedding_dimensions=int(os.getenv("SUPPORT_EVAL_EMBEDDING_DIMENSIONS", "1536"))))
                content = document["text"].encode()
                await repository.ingest(Document(organization_id=owner, knowledge_base_id=kb,
                    document_id=document["document_id"], title=document["title"], source="w21-frozen-fixture"),
                    content, lambda content=content: chunk_sections(parse_source(content, ".md")), embedder.aembed_documents)
            start = time.monotonic()
            response = await operator.post("/support-api/tickets", json={"subject": case.subject, "description": case.description, "knowledge_base_id": kb})
            response.raise_for_status()
            ticket_id = response.json()["ticket_id"]
            key = str(uuid4())
            response = await operator.post(f"/support-api/tickets/{ticket_id}/runs", headers={"Idempotency-Key": key})
            response.raise_for_status()
            run = response.json()
            run_id = run["run_id"]
            if case.scenario == "cancel":
                response = await operator.post(f"/support-api/runs/{run_id}/cancel")
                response.raise_for_status()
            decisions = iter(case.decisions)
            decided = set()
            approval_seen = False
            async def wait_for_run():
                nonlocal run, approval_seen
                while True:
                    response = await operator.get(f"/support-api/runs/{run_id}")
                    response.raise_for_status()
                    run = response.json()
                    if run["status"] in {"succeeded", "failed", "cancelled"}:
                        return
                    if run["status"] == "waiting_approval":
                        approval_seen = True
                        proposal = run["projection"]["proposal_hash"]
                        if proposal not in decided:
                            decision = next(decisions, None)
                            if decision is None:
                                return
                            response = await approver.post(f"/support-api/runs/{run_id}/approval", json={
                                "decision": decision, "proposal_hash": proposal,
                                "feedback": None if decision == "approve" else "请重新核对政策"})
                            response.raise_for_status()
                            decided.add(proposal)
                    await asyncio.sleep(0.5)
            await asyncio.wait_for(wait_for_run(), manifest["budget"]["timeout_seconds"])
            if case.scenario == "replay":
                response = await operator.post(f"/support-api/tickets/{ticket_id}/runs", headers={"Idempotency-Key": key})
                response.raise_for_status()
                if response.json()["run_id"] != run_id:
                    raise ValueError("Repeated request created a different run")
            # Waiting-approval snapshots cannot stream until done; take a finite persisted JSON snapshot.
            events = []
            cursor = 0
            while cursor < run["sequence"]:
                response = await operator.get(f"/support-api/runs/{run_id}/event-history", params={"after": cursor})
                response.raise_for_status()
                page = response.json()
                if not page:
                    raise ValueError("Persisted event history is incomplete")
                events.extend(page)
                cursor = page[-1]["sequence"]
            response = await operator.get(f"/support-api/runs/{run_id}/audit")
            response.raise_for_status()
            audit = response.json()
            tool_audits = [row for row in audit if row["action"] == "crm_update"]
            projection = run["projection"]
            metrics = projection.get("metrics", {})
            evidence = projection.get("evidence_refs", [])
            rows.append({"case_id": case.id, "source": "production", "scope": "api-worker-postgres-redis-graph",
                "model": model_settings.model, "organization_id": org, "run_id": run_id, "thread_id": run["thread_id"], "ticket_id": ticket_id,
                "graph_status": projection.get("graph_status", run["status"]), "status": run["status"], "category": projection.get("category"),
                "answer": projection.get("draft_response", ""), "evidence": evidence, "approval_required": approval_seen,
                "approval_count": len(decided), "writes": len(tool_audits),
                "unauthorized_writes": len(tool_audits) if not any(row["action"] == "approval" and row["payload"]["decision"] == "approve" for row in audit) else 0,
                "audit": [{"action": row["action"], "idempotency_key": row.get("payload", {}).get("tool_result", {}).get("idempotency_key")} for row in audit],
                "events": events, "model_calls": metrics.get("model_calls"), "cost_usd": None,
                "generation_cost_usd": metrics.get("cost_usd"), "cost_scope": "embedding/fixture costs are unmeasured",
                "input_tokens": metrics.get("input_tokens"), "output_tokens": metrics.get("output_tokens"),
                "context_characters": sum(len(ref["snippet"]) for ref in evidence), "latency_seconds": time.monotonic() - start,
                "trace_id": projection.get("trace_id"), "error_code": projection.get("error_code"),
                # Live timeout injection needs a separately authorized fault harness, not a public API switch.
                "fault_injection_verified": case.scenario != "timeout"})
        return rows
