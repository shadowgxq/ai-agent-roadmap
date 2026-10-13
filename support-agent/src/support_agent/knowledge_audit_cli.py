"""Generate 20 observed answers, then score explicit human citation annotations."""

import argparse
import asyncio
import json
from pathlib import Path

from support_agent.config import AgentSettings
from support_agent.graphs.ticket import draft_response
from support_agent.knowledge.audit import citation_audit_report
from support_agent.knowledge.embeddings import create_embedder
from support_agent.knowledge.evaluation import RetrievalCase
from support_agent.knowledge.retrieval import HybridRetriever
from support_agent.knowledge_cli import environment
from support_agent.models import EvidenceRef
from support_agent.services import create_chat_model


async def generate(args: argparse.Namespace) -> dict:
    database_url, embedding_model, api_key, base_url = environment()
    embedder = create_embedder(model=embedding_model, api_key=api_key, base_url=base_url)
    retriever = HybridRetriever(database_url, embedder.aembed_query,
                                embedding_model=embedding_model, min_similarity=args.min_similarity)
    settings = AgentSettings()
    model = create_chat_model(settings)
    cases = [RetrievalCase.model_validate(row) for row in json.loads(args.cases.read_text())]
    selected = [case for case in cases if case.relevant_documents or case.relevant_chunks][:20]
    if len(selected) < 20:
        raise ValueError("Need at least 20 answerable cases")
    rows = []
    for case in selected:
        result = await retriever.retrieve(case.organization_id, case.knowledge_base_id, case.query)
        refs = [EvidenceRef(source_id=ref.chunk_id, title=ref.document_title, **ref.model_dump())
                for ref in result.fused]
        response = draft_response({"normalized_text": case.query, "evidence_refs": refs}, model=model)
        rows.append({"id": case.id, "query": case.query,
                     "evidence": [ref.model_dump() for ref in result.fused],
                     "answer": response.get("draft_response", ""), "status": response["status"],
                     "citation_invalid_ids": response.get("citation_invalid_ids", []),
                     "reviewer": "", "all_claims_supported": None,
                     "annotations": {cid: {"supports_claim": None, "correct_location": None,
                                           "note": ""} for cid in response.get("citation_ids", [])}})
    return {"model": settings.model, "embedding_model": embedding_model,
            "min_similarity": args.min_similarity, "answers": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["generate", "score"])
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[2] / "evals/retrieval_cases.json")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-similarity", type=float, default=0.35)
    args = parser.parse_args()
    if args.action == "score":
        if args.input is None:
            parser.error("score requires --input with human annotations")
        report = citation_audit_report(json.loads(args.input.read_text())["answers"])
    else:
        report = asyncio.run(generate(args))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"answers", "details"}}, indent=2))
    if args.action == "score":
        raise SystemExit(0 if report["audit_gate_passed"] else 1)


if __name__ == "__main__":
    main()
