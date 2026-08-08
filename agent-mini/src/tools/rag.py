"""把本地代码 RAG 暴露为 Agent 可调用的只读工具。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..rag import load_index, retrieve
from ..rag.indexer import Embedder
from ..rag.models import CodeIndex, RetrievedChunk
from .registry import ToolRegistry


DEFAULT_INDEX_NAME = ".agent-mini/rag-index.json"
MAX_TOP_K = 10
MAX_CHARS_PER_CHUNK = 3_000
MAX_TOTAL_CHARS = 12_000


def _format_results(
    results: list[RetrievedChunk],
    *,
    query: str,
) -> str:
    """把检索结果压缩成适合回填 Context 的文本。"""
    if not results:
        return f"RAG 没有找到与查询相关的代码：{query}"

    sections: list[str] = [f"RAG 查询：{query}"]
    total_chars = len(sections[0])
    for rank, result in enumerate(results, start=1):
        symbol = result.symbol or "<module>"
        content = result.content[:MAX_CHARS_PER_CHUNK]
        if len(result.content) > MAX_CHARS_PER_CHUNK:
            content += "\n...[代码块已截断]..."
        section = (
            f"\n\n[{rank}] score={result.score:.4f}\n"
            f"file={result.path}:{result.start_line}-{result.end_line}\n"
            f"symbol={symbol}\n"
            f"```python\n{content}\n```"
        )
        if total_chars + len(section) > MAX_TOTAL_CHARS:
            sections.append("\n...(RAG 总结果已达到上下文上限)...")
            break
        sections.append(section)
        total_chars += len(section)
    return "".join(sections)


def register_rag_tool(
    registry: ToolRegistry,
    workdir: Path,
    *,
    embedder_factory: Callable[[str], Embedder],
    index_path: Path | None = None,
) -> None:
    """注册绑定到指定工作目录的代码 RAG 搜索工具。"""
    root = workdir.resolve()
    selected_index_path = (
        index_path.resolve()
        if index_path is not None
        else root / DEFAULT_INDEX_NAME
    )
    embedder: Embedder | None = None
    index: CodeIndex | None = None

    @registry.tool
    async def rag_search(query: str, top_k: int = 5) -> str:
        """使用代码语义索引查找相关源码，只读且返回文件位置。

        Args:
            query: 描述需要查找的代码职责、行为或问题。
            top_k: 返回最相关的代码块数量，范围为 1 到 10。
        """
        nonlocal embedder, index
        if not query.strip():
            raise ValueError("query 不能为空")
        if not 1 <= top_k <= MAX_TOP_K:
            raise ValueError(f"top_k 必须在 1 到 {MAX_TOP_K} 之间")

        if index is None:
            index = load_index(selected_index_path)
        if embedder is None:
            embedder = embedder_factory(index.embedding_model)

        results = await retrieve(
            index,
            query,
            embedder,
            top_k=top_k,
        )
        return _format_results(results, query=query.strip())


__all__ = ["register_rag_tool"]
