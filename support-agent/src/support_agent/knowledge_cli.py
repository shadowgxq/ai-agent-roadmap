"""Explicit CLI for W19 ingestion, chunk inspection and ranking comparison."""

import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from support_agent.knowledge.embeddings import create_embedder
from support_agent.knowledge.models import Document, KnowledgeBase
from support_agent.knowledge.parsing import chunk_sections, parse_source
from support_agent.knowledge.repository import KnowledgeRepository
from support_agent.knowledge.retrieval import HybridRetriever
from support_agent.knowledge.schema import initialize_knowledge_schema


def environment() -> tuple[str, str, str, str | None]:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    return (os.environ["SUPPORT_AGENT_DATABASE_URL"],
            os.environ["SUPPORT_AGENT_EMBEDDING_MODEL"],
            os.environ["SUPPORT_AGENT_API_KEY"],
            os.getenv("SUPPORT_AGENT_BASE_URL") or None)


async def execute(args: argparse.Namespace) -> object:
    if args.action == "chunks":
        content = args.file.read_bytes()
        return [chunk.model_dump() for chunk in chunk_sections(
            parse_source(content, args.file.suffix), max_tokens=args.max_tokens)]
    if args.action == "init":
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        database_url = os.environ["SUPPORT_AGENT_DATABASE_URL"]
        await initialize_knowledge_schema(database_url)
        return {"schema": "initialized"}
    database_url, model, api_key, base_url = environment()
    embedder = create_embedder(model=model, api_key=api_key, base_url=base_url)
    repository = KnowledgeRepository(database_url)
    if args.action == "ingest":
        await repository.create_base(KnowledgeBase(
            organization_id=args.organization, knowledge_base_id=args.kb, name=args.kb,
            embedding_model=model, embedding_dimensions=args.dimensions,
            pipeline_version=f"w19-v1-cl100k-{args.max_tokens}-40",
        ))
        content = args.file.read_bytes()
        return (await repository.ingest(Document(
            organization_id=args.organization, knowledge_base_id=args.kb,
            document_id=args.document, title=args.title, source=str(args.file),
        ), content, lambda: chunk_sections(parse_source(content, args.file.suffix),
                                          max_tokens=args.max_tokens),
            embedder.aembed_documents)).model_dump()
    retriever = HybridRetriever(database_url, embedder.aembed_query,
                                embedding_model=model, min_similarity=args.min_similarity)
    result = await retriever.retrieve(args.organization, args.kb, args.query)
    return asdict(result) | {
        branch: [ref.model_dump() for ref in getattr(result, branch)]
        for branch in ("vector", "fts", "fused")
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "chunks", "ingest", "search"])
    parser.add_argument("--file", type=Path)
    parser.add_argument("--organization")
    parser.add_argument("--kb")
    parser.add_argument("--document")
    parser.add_argument("--title")
    parser.add_argument("--query")
    parser.add_argument("--dimensions", type=int, default=1536)
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--min-similarity", type=float, default=0.35)
    args = parser.parse_args()
    required = {"chunks": ["file"], "ingest": ["file", "organization", "kb", "document", "title"],
                "search": ["organization", "kb", "query"], "init": []}
    for name in required[args.action]:
        if getattr(args, name) is None:
            parser.error(f"{args.action} requires --{name}")
    print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
