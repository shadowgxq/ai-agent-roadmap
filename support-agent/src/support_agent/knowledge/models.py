"""Tenant-scoped W19 knowledge contracts."""

from pydantic import BaseModel, Field


class KnowledgeBase(BaseModel):
    organization_id: str = Field(min_length=1)
    knowledge_base_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_dimensions: int = Field(gt=0)
    # Changing parser/chunker configuration must also invalidate the content cache.
    pipeline_version: str = Field(default="w19-v1", min_length=1)


class Document(BaseModel):
    organization_id: str = Field(min_length=1)
    knowledge_base_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)


class DocumentVersion(BaseModel):
    document: Document
    version: int = Field(gt=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ChunkDraft(BaseModel):
    text: str = Field(min_length=1)
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = Field(default=None, gt=0)


class EvidenceRef(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    document_version: int
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = None
    snippet: str
    score: float


class IngestionResult(BaseModel):
    document_id: str
    version: int
    chunk_count: int
    reused: bool
