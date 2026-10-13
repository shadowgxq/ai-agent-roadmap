"""Composite foreign keys keep knowledge identities within their tenant."""

from psycopg import AsyncConnection


KNOWLEDGE_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS knowledge_bases (
    organization_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    name TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    pipeline_version TEXT NOT NULL,
    PRIMARY KEY (organization_id, knowledge_base_id)
);
CREATE TABLE IF NOT EXISTS knowledge_documents (
    organization_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    active_version INTEGER,
    PRIMARY KEY (organization_id, knowledge_base_id, document_id),
    FOREIGN KEY (organization_id, knowledge_base_id)
        REFERENCES knowledge_bases (organization_id, knowledge_base_id)
);
CREATE TABLE IF NOT EXISTS knowledge_versions (
    organization_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, knowledge_base_id, document_id, version),
    UNIQUE (organization_id, knowledge_base_id, document_id, content_hash),
    FOREIGN KEY (organization_id, knowledge_base_id, document_id)
        REFERENCES knowledge_documents (organization_id, knowledge_base_id, document_id)
);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    organization_id TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    chunk_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    content TEXT NOT NULL,
    heading_path JSONB NOT NULL,
    page INTEGER CHECK (page > 0),
    embedding vector NOT NULL,
    search_vector tsvector NOT NULL,
    PRIMARY KEY (organization_id, knowledge_base_id, chunk_id),
    UNIQUE (organization_id, knowledge_base_id, document_id, version, ordinal),
    FOREIGN KEY (organization_id, knowledge_base_id, document_id, version)
        REFERENCES knowledge_versions (organization_id, knowledge_base_id, document_id, version)
);
CREATE INDEX IF NOT EXISTS knowledge_chunks_scope
    ON knowledge_chunks (organization_id, knowledge_base_id, document_id, version);
CREATE INDEX IF NOT EXISTS knowledge_chunks_fts
    ON knowledge_chunks USING gin (search_vector);
"""


async def initialize_knowledge_schema(database_url: str) -> None:
    async with await AsyncConnection.connect(database_url) as connection:
        await connection.execute(KNOWLEDGE_SCHEMA)
