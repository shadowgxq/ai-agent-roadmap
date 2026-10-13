"""Atomic ingestion: serialize each document, embed once, publish last."""

from collections.abc import Awaitable, Callable, Sequence
from hashlib import sha256
import json
import math
from uuid import NAMESPACE_URL, uuid5

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import ChunkDraft, Document, IngestionResult, KnowledgeBase


EmbedDocuments = Callable[[list[str]], Awaitable[list[list[float]]]]
BuildChunks = Callable[[], Sequence[ChunkDraft]]


def vector_literal(values: Sequence[float], dimensions: int) -> str:
    if len(values) != dimensions or not all(math.isfinite(v) for v in values):
        raise ValueError("Embedding dimensions or values do not match the knowledge base")
    if not any(values):
        raise ValueError("Cosine retrieval requires a nonzero embedding")
    return "[" + ",".join(str(float(value)) for value in values) + "]"


class KnowledgeRepository:
    def __init__(self, database_url: str):
        self.database_url = database_url

    async def create_base(self, base: KnowledgeBase) -> None:
        async with await AsyncConnection.connect(self.database_url, row_factory=dict_row) as conn:
            await conn.execute(
                """INSERT INTO knowledge_bases VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (organization_id, knowledge_base_id) DO NOTHING""",
                (base.organization_id, base.knowledge_base_id, base.name,
                 base.embedding_model, base.embedding_dimensions, base.pipeline_version),
            )
            cursor = await conn.execute(
                "SELECT * FROM knowledge_bases WHERE organization_id=%s AND knowledge_base_id=%s",
                (base.organization_id, base.knowledge_base_id),
            )
            stored = await cursor.fetchone()
            if any(stored[key] != getattr(base, key) for key in (
                "embedding_model", "embedding_dimensions", "pipeline_version"
            )):
                raise ValueError("Existing KB configuration differs; create a new KB for reindexing")

    async def ingest(
        self, document: Document, content: bytes, build_chunks: BuildChunks,
        embed: EmbedDocuments,
    ) -> IngestionResult:
        scope = (document.organization_id, document.knowledge_base_id, document.document_id)
        async with await AsyncConnection.connect(self.database_url, row_factory=dict_row) as conn:
            # Transaction lock spans chunking and embedding to avoid duplicate provider calls.
            # Provider timeouts belong to the injected embedder; failure rolls back publication.
            lock_key = json.dumps(scope, ensure_ascii=False)
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
            cursor = await conn.execute(
                "SELECT * FROM knowledge_bases WHERE organization_id=%s AND knowledge_base_id=%s",
                scope[:2],
            )
            base = await cursor.fetchone()
            if base is None:
                raise LookupError("Knowledge base not found in the requested tenant")
            signature = json.dumps({
                "embedding_model": base["embedding_model"],
                "dimensions": base["embedding_dimensions"],
                "pipeline": base["pipeline_version"],
                "title": document.title, "source": document.source,
            }, sort_keys=True).encode()
            content_hash = sha256(signature + b"\0" + content).hexdigest()
            await conn.execute(
                """INSERT INTO knowledge_documents
                   (organization_id,knowledge_base_id,document_id,title,source)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (*scope, document.title, document.source),
            )
            cursor = await conn.execute(
                """SELECT v.version, count(c.chunk_id) AS chunk_count
                   FROM knowledge_versions v LEFT JOIN knowledge_chunks c
                     USING (organization_id,knowledge_base_id,document_id,version)
                   WHERE v.organization_id=%s AND v.knowledge_base_id=%s
                     AND v.document_id=%s AND v.content_hash=%s
                   GROUP BY v.version""", (*scope, content_hash),
            )
            existing = await cursor.fetchone()
            if existing:
                version, count = existing["version"], existing["chunk_count"]
            else:
                chunks = list(build_chunks())
                if not chunks:
                    raise ValueError("No text chunks; existing active version is unchanged")
                embeddings = await embed([chunk.text for chunk in chunks])
                if len(embeddings) != len(chunks):
                    raise ValueError("Embedding provider returned the wrong batch size")
                vectors = [vector_literal(v, base["embedding_dimensions"]) for v in embeddings]
                cursor = await conn.execute(
                    """SELECT COALESCE(max(version),0)+1 AS version FROM knowledge_versions
                       WHERE organization_id=%s AND knowledge_base_id=%s AND document_id=%s""", scope,
                )
                version = (await cursor.fetchone())["version"]
                await conn.execute(
                    """INSERT INTO knowledge_versions
                       (organization_id,knowledge_base_id,document_id,version,content_hash,title,source)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (*scope, version, content_hash, document.title, document.source),
                )
                for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                    chunk_id = str(uuid5(NAMESPACE_URL, json.dumps((*scope, version, ordinal))))
                    await conn.execute(
                        """INSERT INTO knowledge_chunks
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,
                                   to_tsvector('simple',%s))""",
                        (*scope, version, chunk_id, ordinal, chunk.text,
                         Jsonb(chunk.heading_path), chunk.page, vector, chunk.text),
                    )
                count = len(chunks)
            await conn.execute(
                """UPDATE knowledge_documents SET active_version=%s,title=%s,source=%s
                   WHERE organization_id=%s AND knowledge_base_id=%s AND document_id=%s""",
                (version, document.title, document.source, *scope),
            )
            return IngestionResult(document_id=document.document_id, version=version,
                                   chunk_count=count, reused=existing is not None)
