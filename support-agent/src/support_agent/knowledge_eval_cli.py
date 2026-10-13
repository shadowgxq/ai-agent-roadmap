"""Run explicitly requested W19 retrieval evals; fixture loading calls embeddings."""

import argparse
import asyncio
import json
from pathlib import Path

from support_agent.knowledge.embeddings import create_embedder
from support_agent.knowledge.evaluation import RetrievalCase, evaluate_retrieval
from support_agent.knowledge.models import Document, KnowledgeBase
from support_agent.knowledge.parsing import chunk_sections, parse_source
from support_agent.knowledge.repository import KnowledgeRepository
from support_agent.knowledge.retrieval import HybridRetriever
from support_agent.knowledge.schema import initialize_knowledge_schema
from support_agent.knowledge_cli import environment


PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def run(args: argparse.Namespace) -> dict:
    database_url, model, api_key, base_url = environment()
    embedder = create_embedder(model=model, api_key=api_key, base_url=base_url)
    if args.load_fixtures:
        await initialize_knowledge_schema(database_url)
        repository = KnowledgeRepository(database_url)
        for row in json.loads(args.corpus.read_text()):
            await repository.create_base(KnowledgeBase(
                organization_id=row["organization_id"], knowledge_base_id=row["knowledge_base_id"],
                name="W19 isolated eval policy", embedding_model=model,
                embedding_dimensions=args.dimensions, pipeline_version="w19-v1-cl100k-400-40",
            ))
            content = row["text"].encode()
            await repository.ingest(Document(
                **{key: row[key] for key in ("organization_id", "knowledge_base_id", "document_id", "title")},
                source=f"fixture:{row['document_id']}",
            ), content, lambda content=content: chunk_sections(parse_source(content, ".md")),
                embedder.aembed_documents)
    cases = [RetrievalCase.model_validate(row) for row in json.loads(args.cases.read_text())]
    return await evaluate_retrieval(HybridRetriever(
        database_url, embedder.aembed_query, embedding_model=model,
        min_similarity=args.min_similarity), cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "evals/retrieval_cases.json")
    parser.add_argument("--corpus", type=Path, default=PROJECT_ROOT / "evals/policy_corpus.json")
    parser.add_argument("--load-fixtures", action="store_true", help="Explicitly embed and persist eval corpus")
    parser.add_argument("--dimensions", type=int, default=1536)
    parser.add_argument("--min-similarity", type=float, default=0.35)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "observations"}, indent=2))
    raise SystemExit(0 if report["retrieval_gate_passed"] else 1)


if __name__ == "__main__":
    main()
