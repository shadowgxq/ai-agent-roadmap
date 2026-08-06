"""使用余弦相似度从内存向量索引中检索代码。"""

import math

from .indexer import Embedder
from .models import CodeIndex, RetrievedChunk


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个等长向量的余弦相似度。"""
    if len(left) != len(right):
        raise ValueError("向量维度不一致")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    return dot_product / (left_norm * right_norm)


async def retrieve(
    index: CodeIndex,
    query: str,
    embedder: Embedder,
    *,
    top_k: int = 5,
    min_score: float = -1.0,
) -> list[RetrievedChunk]:
    """生成查询向量，返回相似度最高的 top-k 代码块。"""
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空")
    if top_k < 1:
        raise ValueError("top_k 必须大于 0")
    if not -1 <= min_score <= 1:
        raise ValueError("min_score 必须在 -1 和 1 之间")
    if embedder.model != index.embedding_model:
        raise ValueError(
            "查询 embedding 模型必须与建索引时一致: "
            f"{embedder.model} != {index.embedding_model}"
        )

    vectors = await embedder.embed([query])
    query_vector = vectors[0]
    if len(query_vector) != index.dimension:
        raise ValueError("查询向量维度与索引维度不一致")

    ranked = sorted(
        (
            (cosine_similarity(query_vector, chunk.embedding), chunk)
            for chunk in index.chunks
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        RetrievedChunk(
            score=score,
            path=chunk.path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            symbol=chunk.symbol,
            kind=chunk.kind,
            content=chunk.content,
        )
        for score, chunk in ranked[:top_k]
        if score >= min_score
    ]
