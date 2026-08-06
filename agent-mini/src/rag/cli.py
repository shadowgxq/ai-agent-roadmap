"""构建代码索引并执行最小 RAG 查询。"""

import argparse
import asyncio
from pathlib import Path

from openai import AsyncOpenAI

from ..agent.config import AgentSettings, PROJECT_ROOT
from .embeddings import OpenAIEmbedder
from .indexer import build_index, load_index, save_index
from .retriever import retrieve


DEFAULT_INDEX_PATH = PROJECT_ROOT / ".agent-mini" / "rag-index.json"


def parse_args() -> argparse.Namespace:
    """解析 index/search 两个子命令。"""
    parser = argparse.ArgumentParser(description="构建和查询代码 RAG 索引")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="构建代码向量索引")
    index_parser.add_argument("root", type=Path, help="需要索引的代码目录")
    index_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="索引 JSON 输出路径",
    )
    index_parser.add_argument(
        "--model",
        default=None,
        help="覆盖 EMBEDDING_MODEL",
    )
    index_parser.add_argument(
        "--max-lines",
        type=int,
        default=200,
        help="模块级退化切块的最大行数",
    )

    search_parser = subparsers.add_parser("search", help="查询已有索引")
    search_parser.add_argument("query", help="自然语言或代码查询")
    search_parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="需要查询的索引 JSON",
    )
    search_parser.add_argument("--model", default=None)
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.add_argument("--min-score", type=float, default=-1.0)
    search_parser.add_argument("--show-chars", type=int, default=1500)
    return parser.parse_args()


async def run_cli() -> None:
    """创建 embedding 客户端并执行指定操作。"""
    args = parse_args()
    settings = AgentSettings()
    api_key = settings.embedding_api_key or settings.api_key
    base_url = settings.embedding_base_url or settings.base_url

    async with AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
    ) as client:
        if args.command == "index":
            model = args.model or settings.embedding_model
            embedder = OpenAIEmbedder(
                client,
                model=model,
                batch_size=settings.embedding_batch_size,
            )
            index = await build_index(
                args.root,
                embedder,
                max_lines=args.max_lines,
            )
            output = save_index(index, args.output)
            print(
                f"indexed files={index.file_count} chunks={len(index.chunks)} "
                f"dimension={index.dimension} output={output}"
            )
            return

        index = load_index(args.index)
        model = args.model or index.embedding_model
        embedder = OpenAIEmbedder(
            client,
            model=model,
            batch_size=settings.embedding_batch_size,
        )
        results = await retrieve(
            index,
            args.query,
            embedder,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        if not results:
            print("no results")
            return
        if args.show_chars < 1:
            raise ValueError("show_chars 必须大于 0")

        for rank, result in enumerate(results, start=1):
            symbol = result.symbol or "<module>"
            print(
                f"[{rank}] score={result.score:.4f} "
                f"{result.path}:{result.start_line}-{result.end_line} "
                f"symbol={symbol}"
            )
            print(result.content[:args.show_chars])
            print()


def main() -> None:
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
