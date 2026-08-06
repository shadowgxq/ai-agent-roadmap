"""RAG 索引、代码块和检索结果的数据模型。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ChunkKind = Literal["function", "class", "module"]


class CodeChunk(BaseModel):
    """保留源码位置和语义边界的代码块。"""

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    symbol: str | None = None
    kind: ChunkKind
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> "CodeChunk":
        if self.end_line < self.start_line:
            raise ValueError("end_line 不能小于 start_line")
        return self

    def embedding_text(self) -> str:
        """把来源元数据与源码一起送入 embedding 模型。"""
        symbol = self.symbol or "<module>"
        return (
            f"File: {self.path}\n"
            f"Symbol: {symbol}\n"
            f"Kind: {self.kind}\n\n"
            f"{self.content}"
        )


class IndexedChunk(CodeChunk):
    """附带向量的可检索代码块。"""

    embedding: list[float] = Field(min_length=1)


class CodeIndex(BaseModel):
    """可持久化的最小内存向量索引。"""

    schema_version: int = 1
    root: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    dimension: int = Field(gt=0)
    file_count: int = Field(ge=0)
    chunks: list[IndexedChunk] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_vectors(self) -> "CodeIndex":
        ids = {chunk.id for chunk in self.chunks}
        if len(ids) != len(self.chunks):
            raise ValueError("索引中存在重复 chunk id")
        if any(len(chunk.embedding) != self.dimension for chunk in self.chunks):
            raise ValueError("索引向量维度不一致")
        return self


class RetrievedChunk(BaseModel):
    """返回给调用方的相似代码块，不携带原始向量。"""

    score: float
    path: str
    start_line: int
    end_line: int
    symbol: str | None
    kind: ChunkKind
    content: str
