"""P1 adoption gate: distinguish missing recall from poor candidate ordering."""

import math
from statistics import mean

from .evaluation import RetrievalCase, ranking_metrics
from .models import EvidenceRef


def diagnose_ranking(report: dict) -> dict:
    observations = report.get("observations", [])
    if (len(observations) < 50 or len({row.get("id") for row in observations}) != len(observations)
            or report.get("error_count", 0) or any("error" in row for row in observations)):
        return {"decision": "needs_data", "reason": "Need complete observed baseline rankings"}
    missing, ordering, correct = [], [], []
    for row in report["observations"]:
        if not row.get("relevant_documents") and not row.get("relevant_chunks"):
            continue
        if "candidates" not in row:
            return {"decision": "needs_data", "reason": "Baseline lacks top-20 candidates"}
        chunk_labels = bool(row.get("relevant_chunks"))
        field = "chunk_id" if chunk_labels else "document_id"
        expected = set(row["relevant_chunks"] if chunk_labels else row["relevant_documents"])
        top5 = {ref[field] for ref in row["rankings"]["hybrid"][:5]}
        candidates = {ref[field] for ref in row["candidates"]}
        if expected <= top5:
            correct.append(row["id"])
        elif expected <= candidates:
            ordering.append(row["id"])
        else:
            missing.append(row["id"])
    failures = len(missing) + len(ordering)
    return {"decision": "experiment_allowed" if len(ordering) > len(missing) else "keep_hybrid",
            "reason": "Ordering dominates failures" if len(ordering) > len(missing)
                      else "Improve corpus/chunk/query/filter first, or baseline has no ranking failures",
            "ordering_failures": ordering, "recall_failures": missing,
            "successful_cases": correct, "failure_count": failures}


def compare_reranking(baseline: dict, candidate: dict, *,
                      max_latency_ratio: float = 1.5, max_extra_cost_usd: float = 0.01) -> dict:
    if (not math.isfinite(max_latency_ratio) or not math.isfinite(max_extra_cost_usd)
            or max_latency_ratio < 1 or max_extra_cost_usd < 0):
        raise ValueError("Invalid declared latency/cost budget")
    diagnosis = diagnose_ranking(baseline)
    if diagnosis["decision"] != "experiment_allowed":
        return diagnosis
    candidate_rows = candidate.get("observations", [])
    if candidate.get("error_count", 0) or any("error" in row for row in candidate_rows):
        return {"decision": "reject", "reason": "Candidate has evaluation errors"}
    if len({row.get("id") for row in candidate_rows}) != len(candidate_rows):
        return {"decision": "reject", "reason": "Candidate repeats case IDs"}
    left = {row["id"]: row for row in baseline["observations"]}
    right = {row["id"]: row for row in candidate_rows}
    if left.keys() != right.keys():
        return {"decision": "needs_data", "reason": "Experiments must use the same cases"}
    for key, row in left.items():
        other = right[key]
        for field in ("query", "organization_id", "knowledge_base_id", "relevant_documents", "relevant_chunks"):
            if row.get(field) != other.get(field):
                return {"decision": "reject", "reason": f"Changed case contract: {key}/{field}"}
        snapshot = lambda value: {(ref["chunk_id"], ref["document_version"]) for ref in value.get("candidates", [])}
        if snapshot(row) != snapshot(other):
            return {"decision": "reject", "reason": "Reranking must reorder the same candidate snapshot"}
        frozen_refs = {ref["chunk_id"]: ref for ref in row["candidates"]}
        provenance_fields = ("document_id", "document_title", "document_version", "heading_path", "page", "snippet")
        for ref in other.get("candidates", []) + other.get("rankings", {}).get("hybrid", []):
            original = frozen_refs.get(ref["chunk_id"])
            if original is None or any(ref.get(field) != original.get(field) for field in provenance_fields):
                return {"decision": "reject", "reason": "Candidate altered frozen evidence content or provenance"}
        allowed = snapshot(row)
        if any((ref["chunk_id"], ref["document_version"]) not in allowed
               for ref in other.get("rankings", {}).get("hybrid", [])):
            return {"decision": "reject", "reason": "Candidate returned evidence outside the frozen pool"}
        # Cost must be recorded by the runner/provider, never guessed from model names.
        if "cost_usd" not in row or "cost_usd" not in other:
            return {"decision": "needs_data", "reason": "Missing measured per-case cost"}
        if "latency_seconds" not in row or "latency_seconds" not in other:
            return {"decision": "needs_data", "reason": "Missing measured per-case latency"}
        for observation in (row, other):
            for field in ("cost_usd", "latency_seconds"):
                value = observation[field]
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0
                        or (field == "latency_seconds" and value == 0)):
                    return {"decision": "reject", "reason": "Invalid measured cost or latency"}
    if baseline.get("embedding_model") != candidate.get("embedding_model"):
        return {"decision": "reject", "reason": "Embedding model changed alongside reranking"}
    if baseline.get("min_similarity") != candidate.get("min_similarity"):
        return {"decision": "reject", "reason": "Retrieval threshold changed alongside reranking"}
    def measured_summary(observations: dict[str, dict]) -> dict:
        metrics, absent = [], []
        for row in observations.values():
            refs = [EvidenceRef.model_validate(ref) for ref in row["rankings"]["hybrid"][:5]]
            case = RetrievalCase.model_validate(row)
            if case.relevant_documents or case.relevant_chunks:
                metrics.append(ranking_metrics(refs, case))
            else:
                absent.append(bool(refs))
        if not metrics:
            raise ValueError("Missing answerable observations")
        return {"recall@5": mean(value["recall@5"] for value in metrics),
                "mrr": mean(value["mrr"] for value in metrics),
                "no_answer_false_positive_rate": mean(absent) if absent else None}

    before, after = measured_summary(left), measured_summary(right)
    gain = max(after["recall@5"] - before["recall@5"], after["mrr"] - before["mrr"])
    base_latency = mean(row["latency_seconds"] for row in left.values())
    new_latency = mean(row["latency_seconds"] for row in right.values())
    extra_cost = mean(right[key]["cost_usd"] - row["cost_usd"] for key, row in left.items())
    false_positive_ok = (
        before.get("no_answer_false_positive_rate") is not None
        and after.get("no_answer_false_positive_rate") is not None
        and after["no_answer_false_positive_rate"] <= before["no_answer_false_positive_rate"]
    )
    adopted = (gain >= 0.05 and new_latency <= base_latency * max_latency_ratio
               and extra_cost <= max_extra_cost_usd and false_positive_ok)
    return {"decision": "adopt" if adopted else "reject", "quality_gain": gain,
            "baseline_mean_latency": base_latency, "candidate_mean_latency": new_latency,
            "mean_extra_cost_usd": extra_cost, "no_answer_nonregression": false_positive_ok,
            "max_latency_ratio": max_latency_ratio, "max_extra_cost_usd": max_extra_cost_usd}
