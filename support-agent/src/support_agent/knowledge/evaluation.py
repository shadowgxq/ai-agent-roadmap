"""Retrieval metrics are calculated from observed rankings, never fixture labels alone."""

from collections.abc import Sequence
from statistics import mean
import time

from pydantic import BaseModel, Field

from .models import EvidenceRef
from .retrieval import HybridRetriever


class RetrievalCase(BaseModel):
    id: str
    query: str
    relevant_documents: list[str]
    relevant_chunks: list[str] = Field(default_factory=list)
    kind: str = "answerable"
    organization_id: str = "eval-org-a"
    knowledge_base_id: str = "policy"


def ranking_metrics(refs: Sequence[EvidenceRef], case: RetrievalCase) -> dict[str, float]:
    expected = set(case.relevant_chunks or case.relevant_documents)
    # The corpus labels documents; multiple chunks from one document count once.
    ranked = [ref.chunk_id if case.relevant_chunks else ref.document_id for ref in refs]
    recalls = {f"recall@{k}": len(set(ranked[:k]) & expected) / len(expected)
               for k in (1, 3, 5)} if expected else {}
    first = next((rank for rank, item in enumerate(ranked, 1) if item in expected), None)
    return recalls | {"mrr": 1 / first if first else 0.0}


async def evaluate_retrieval(retriever: HybridRetriever, cases: list[RetrievalCase]) -> dict:
    if len(cases) < 50 or len({case.id for case in cases}) != len(cases):
        raise ValueError("W19 requires at least 50 uniquely identified retrieval cases")
    observations = []
    for case in cases:
        start = time.monotonic()
        try:
            result = await retriever.retrieve(case.organization_id, case.knowledge_base_id,
                                              case.query, limit=5)
        except Exception as exc:
            observations.append({"id": case.id, "error": type(exc).__name__,
                                 "latency_seconds": time.monotonic() - start})
            continue
        rankings = {"vector_only": result.vector[:5], "hybrid": result.fused}
        observations.append({
            "id": case.id, "query": case.query, "kind": case.kind,
            "organization_id": case.organization_id, "knowledge_base_id": case.knowledge_base_id,
            "relevant_documents": case.relevant_documents, "relevant_chunks": case.relevant_chunks,
            "latency_seconds": time.monotonic() - start, "fallback": result.fallback,
            "rankings": {name: [ref.model_dump() for ref in refs] for name, refs in rankings.items()},
            "metrics": {name: ranking_metrics(refs, case) for name, refs in rankings.items()},
        })
    by_id = {row["id"]: row for row in observations}
    answerable = [case for case in cases if case.relevant_documents or case.relevant_chunks]
    absent = [case for case in cases if not case.relevant_documents and not case.relevant_chunks]
    if not answerable or not absent:
        raise ValueError("Dataset must include answerable and no-answer cases")
    summary = {}
    for branch in ("vector_only", "hybrid"):
        summary[branch] = {
            metric: mean(by_id[case.id].get("metrics", {}).get(branch, {}).get(metric, 0.0)
                         for case in answerable)
            for metric in ("recall@1", "recall@3", "recall@5", "mrr")
        }
        measured_absent = [by_id[case.id] for case in absent if "error" not in by_id[case.id]]
        summary[branch]["no_answer_false_positive_rate"] = (
            mean(bool(row["rankings"][branch]) for row in measured_absent)
            if measured_absent else None
        )
        summary[branch]["no_answer_measured_cases"] = len(measured_absent)
    errors = sum("error" in row for row in observations)
    return {"case_count": len(cases), "answerable_count": len(answerable),
            "no_answer_count": len(absent), "error_count": errors,
            "embedding_model": retriever.embedding_model,
            "min_similarity": retriever.min_similarity, "summary": summary,
            "retrieval_gate_passed": errors == 0 and summary["hybrid"]["recall@5"] >= 0.8,
            "observations": observations}
