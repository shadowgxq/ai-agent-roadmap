"""Tenant-filtered exact vector + PostgreSQL FTS retrieval with RRF."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import re
import unicodedata

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .models import EvidenceRef
from .repository import vector_literal


EmbedQuery = Callable[[str], Awaitable[list[float]]]
STOP_WORDS = frozenset("a an the and or of to in on for is are be with this that it".split())


def search_terms(text: str) -> list[str]:
    """Simple English lexemes and CJK bigrams without a second database extension."""
    terms = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
    return list(dict.fromkeys(term for term in terms if term not in STOP_WORDS))


def searchable_text(text: str) -> str:
    return " ".join(search_terms(text))


@dataclass
class RetrievalResult:
    query: str
    organization_id: str
    knowledge_base_id: str
    vector: list[EvidenceRef] = field(default_factory=list)
    fts: list[EvidenceRef] = field(default_factory=list)
    fused: list[EvidenceRef] = field(default_factory=list)
    fallback: str | None = None


def reciprocal_rank_fusion(vector: list[EvidenceRef], fts: list[EvidenceRef],
                           *, limit: int = 5, constant: int = 60) -> list[EvidenceRef]:
    scores: dict[str, float] = {}
    refs: dict[str, EvidenceRef] = {}
    for ranking in (vector, fts):
        seen: set[str] = set()
        for rank, ref in enumerate(ranking, 1):
            if ref.chunk_id in seen:
                continue
            seen.add(ref.chunk_id)
            refs[ref.chunk_id] = ref
            scores[ref.chunk_id] = scores.get(ref.chunk_id, 0) + 1 / (constant + rank)
    ordered = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
    return [refs[key].model_copy(update={"score": scores[key]}) for key in ordered]


# Both ranking branches restrict scope BEFORE LIMIT. Exact search is adequate for
# the learning corpus and avoids approximate-index post-filter recall surprises.
SCOPED_CHUNKS = """
    FROM knowledge_chunks c
    JOIN knowledge_documents d
      ON d.organization_id=c.organization_id AND d.knowledge_base_id=c.knowledge_base_id
     AND d.document_id=c.document_id AND d.active_version=c.version
    JOIN knowledge_versions v
      ON v.organization_id=c.organization_id AND v.knowledge_base_id=c.knowledge_base_id
     AND v.document_id=c.document_id AND v.version=c.version
    WHERE c.organization_id=%s AND c.knowledge_base_id=%s
"""
FIELDS = """c.chunk_id,c.document_id,v.title AS document_title,
            c.version AS document_version,c.heading_path,c.page,c.content AS snippet"""


class HybridRetriever:
    def __init__(self, database_url: str, embed_query: EmbedQuery, *,
                 embedding_model: str, min_similarity: float = 0.35):
        if not -1 <= min_similarity <= 1:
            raise ValueError("min_similarity must be in [-1,1]")
        self.database_url = database_url
        self.embed_query = embed_query
        self.embedding_model = embedding_model
        self.min_similarity = min_similarity

    async def retrieve(self, organization_id: str, knowledge_base_id: str,
                       query: str, *, limit: int = 5) -> RetrievalResult:
        query = " ".join(unicodedata.normalize("NFKC", query).split())
        result = RetrievalResult(query, organization_id, knowledge_base_id)
        if not organization_id.strip() or not knowledge_base_id.strip():
            raise ValueError("Explicit tenant and knowledge base are required")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        if not query:
            result.fallback = "empty_query"
            return result
        if len(query) > 8000:
            raise ValueError("Query exceeds the 8000-character budget")
        if not search_terms(query):
            result.fallback = "no_searchable_terms"
            return result
        scope = (organization_id, knowledge_base_id)
        async with await AsyncConnection.connect(self.database_url, row_factory=dict_row) as conn:
            # Use one read snapshot so an active-version switch cannot mix rankings.
            await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor = await conn.execute(
                "SELECT * FROM knowledge_bases WHERE organization_id=%s AND knowledge_base_id=%s", scope,
            )
            base = await cursor.fetchone()
            if base is None:
                raise LookupError("Knowledge base not found in the requested tenant")
            if base["embedding_model"] != self.embedding_model:
                raise ValueError("Query embedding model differs from the indexed model")
            terms = search_terms(query)
            if terms:
                tsquery = " | ".join(terms)
                cursor = await conn.execute(
                    f"""SELECT {FIELDS}, ts_rank_cd(c.search_vector,to_tsquery('simple',%s)) AS score
                        {SCOPED_CHUNKS}
                        AND c.search_vector @@ to_tsquery('simple',%s)
                        ORDER BY score DESC,c.chunk_id LIMIT 20""", (tsquery, *scope, tsquery),
                )
                result.fts = [EvidenceRef.model_validate(row) for row in await cursor.fetchall()]
            try:
                vector = vector_literal(await self.embed_query(query), base["embedding_dimensions"])
            except Exception:
                # Do not leak provider error bodies or secrets into application events.
                result.fallback = "embedding_failed_fts_only"
            else:
                cursor = await conn.execute(
                    f"""SELECT {FIELDS}, 1-(c.embedding <=> %s::vector) AS score
                        {SCOPED_CHUNKS}
                        AND 1-(c.embedding <=> %s::vector) >= %s
                        ORDER BY c.embedding <=> %s::vector,c.chunk_id LIMIT 20""",
                    (vector, *scope, vector, self.min_similarity, vector),
                )
                result.vector = [EvidenceRef.model_validate(row) for row in await cursor.fetchall()]
            result.fused = reciprocal_rank_fusion(result.vector, result.fts, limit=limit)
        return result
