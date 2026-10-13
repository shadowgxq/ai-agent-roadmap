"""Human grounding review is separate from syntactic citation validation."""

from .citations import ABSTENTION, validate_citations


def citation_audit_report(rows: list[dict]) -> dict:
    if len(rows) < 20 or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("At least 20 distinct answers must be audited")
    completed, correct, details = 0, 0, []
    for row in rows:
        allowed = {ref["chunk_id"] for ref in row["evidence"]}
        validation = validate_citations(row["answer"], allowed)
        annotations = row.get("annotations", {})
        reviewed = bool(row.get("reviewer", "").strip()) and isinstance(row.get("all_claims_supported"), bool)
        reviewed = reviewed and all(
            isinstance(annotations.get(cid, {}).get("supports_claim"), bool)
            and isinstance(annotations.get(cid, {}).get("correct_location"), bool)
            for cid in validation.cited_ids
        )
        passed = (
            reviewed and validation.valid and row.get("status") == "drafted"
            and not row.get("citation_invalid_ids") and row["answer"] != ABSTENTION
            and row["all_claims_supported"] is True
            and all(annotations[cid]["supports_claim"] and annotations[cid]["correct_location"]
                    for cid in validation.cited_ids)
        )
        completed += int(reviewed)
        correct += int(passed)
        details.append({"id": row["id"], "reviewed": reviewed, "passed": passed,
                        "invalid_ids": list(validation.invalid_ids)})
    return {"answer_count": len(rows), "reviewed_count": completed,
            "correct_answers": correct, "citation_correctness": correct / len(rows),
            "audit_gate_passed": completed == len(rows) and correct / len(rows) >= 0.9,
            "details": details}
