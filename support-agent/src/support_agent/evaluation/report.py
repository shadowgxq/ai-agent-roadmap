"""Deterministic evidence assertions; missing production measurements stay null."""

from collections import Counter
import math
from statistics import mean

from support_agent.knowledge.citations import ABSTENTION, validate_citations
from .catalog import E2ECase


def assess(case: E2ECase, observation: dict) -> dict:
    failures = []
    expected = case.expected
    if observation.get("category") != expected.category and case.scenario != "timeout":
        failures.append("classification")
    if observation.get("graph_status") != expected.graph_status:
        failures.append("infra")
    refs = observation.get("evidence", [])
    actual_docs = {ref.get("document_id") for ref in refs}
    if not set(expected.documents) <= actual_docs or (not expected.documents and refs):
        failures.append("retrieval")
    citation = validate_citations(observation.get("answer", ""), {ref["source_id"] for ref in refs})
    if refs and not citation.valid:
        failures.append("grounding")
    if expected.graph_status == "abstained" and observation.get("answer") != ABSTENTION:
        failures.append("grounding")
    if observation.get("approval_required") != expected.approval_required:
        failures.append("approval")
    if observation.get("writes") != expected.writes:
        failures.append("tool")
    if observation.get("unauthorized_writes", 0):
        failures.append("security")
    tool_audits = [row for row in observation.get("audit", []) if row["action"] == "crm_update"]
    if (len(tool_audits) != observation.get("writes")
            or len({row["idempotency_key"] for row in tool_audits}) != len(tool_audits)):
        failures.append("tool")
    if observation.get("writes", 0) and not observation.get("approval_count", 0):
        failures.append("approval")
    sequences = [event["sequence"] for event in observation.get("events", [])]
    terminal = observation.get("status") in {"succeeded", "failed", "cancelled"}
    done = sum(event["kind"] == "done" for event in observation.get("events", []))
    if sequences != list(range(1, len(sequences) + 1)) or done != int(terminal):
        failures.append("infra")
    return {"case_id": case.id, "passed": not failures, "failure_categories": sorted(set(failures)),
            "citation_ids_valid": citation.valid if refs else None}


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * quantile) - 1)]


def make_report(manifest: dict, cases: list[E2ECase], observations: list[dict]) -> dict:
    required = {"case_id", "source", "scope", "run_id", "thread_id", "ticket_id", "organization_id",
                "graph_status", "status", "category", "answer", "evidence", "approval_required",
                "approval_count", "writes", "unauthorized_writes", "audit", "events", "latency_seconds", "cost_usd"}
    for row in observations:
        if not required <= row.keys():
            raise ValueError("Incomplete observation cannot be scored")
        for metric in ("latency_seconds", "cost_usd"):
            value = row[metric]
            if value is None and metric == "cost_usd":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid observed latency or cost")
    if len({row["run_id"] for row in observations}) != len(observations) or len({row["thread_id"] for row in observations}) != len(observations):
        raise ValueError("Eval cases reused run/checkpoint identities")
    by_id = {row["case_id"]: row for row in observations}
    if len(by_id) != len(observations) or set(by_id) != {case.id for case in cases}:
        raise ValueError("Every frozen case needs exactly one observed result")
    results = [assess(case, by_id[case.id]) for case in cases]
    sources = {row["source"] for row in observations}
    if len(sources) != 1:
        raise ValueError("Offline and production observations must not be mixed")
    latency = [row["latency_seconds"] for row in observations]
    cost = [row["cost_usd"] for row in observations if row.get("cost_usd") is not None]
    citations = [row["citation_ids_valid"] for row in results if row["citation_ids_valid"] is not None]
    return {"version": manifest["version"], "snapshots": manifest["snapshots"], "source": next(iter(sources)),
            "case_count": len(cases), "passed_count": sum(row["passed"] for row in results),
            "success_rate": mean(row["passed"] for row in results),
            "citation_id_validity": mean(citations) if citations else None,
            "citation_correctness": None, "citation_review": "requires independent claim-support annotations",
            "tool_approval_violations": sum(row.get("unauthorized_writes", 0) for row in observations),
            "average_cost_usd": mean(cost) if len(cost) == len(cases) else None,
            "cost_measured_cases": len(cost), "p50_latency_seconds": percentile(latency, 0.5),
            "p95_latency_seconds": percentile(latency, 0.95),
            "failure_categories": dict(Counter(category for row in results for category in row["failure_categories"])),
            "production_quality_verified": False,
            "results": results, "observations": observations}
