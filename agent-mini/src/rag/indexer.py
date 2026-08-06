"""按 Python 语义边界切块，并构建可持久化向量索引。"""

import ast
import hashlib
import os
from pathlib import Path
from typing import Protocol

from .models import ChunkKind, CodeChunk, CodeIndex, IndexedChunk


IGNORED_DIRS = frozenset(
    {
        ".agent-mini",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
SYMBOL_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class Embedder(Protocol):
    """索引器只依赖最小 embedding 能力。"""

    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def discover_python_files(root: Path) -> list[Path]:
    """发现 Python 文件，并跳过依赖、缓存和已有索引目录。"""
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"索引根目录不存在或不是目录: {root}")

    files: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in IGNORED_DIRS
        )
        current_path = Path(current)
        files.extend(
            current_path / name
            for name in sorted(filenames)
            if name.endswith(".py")
        )
    return files


def _node_start(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", [])
    return min(
        [getattr(node, "lineno", 1), *[item.lineno for item in decorators]]
    )


def _chunk_id(
    relative_path: str,
    start_line: int,
    end_line: int,
    symbol: str | None,
    content: str,
) -> str:
    payload = (
        f"{relative_path}:{start_line}:{end_line}:{symbol or ''}:{content}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _make_chunk(
    *,
    relative_path: str,
    lines: list[str],
    start_line: int,
    end_line: int,
    symbol: str | None,
    kind: ChunkKind,
) -> CodeChunk | None:
    content = "\n".join(lines[start_line - 1:end_line]).strip()
    if not content:
        return None
    return CodeChunk(
        id=_chunk_id(
            relative_path,
            start_line,
            end_line,
            symbol,
            content,
        ),
        path=relative_path,
        start_line=start_line,
        end_line=end_line,
        symbol=symbol,
        kind=kind,
        content=content,
    )


def _line_chunks(
    *,
    relative_path: str,
    lines: list[str],
    start_line: int,
    end_line: int,
    max_lines: int,
) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    for chunk_start in range(start_line, end_line + 1, max_lines):
        chunk_end = min(chunk_start + max_lines - 1, end_line)
        chunk = _make_chunk(
            relative_path=relative_path,
            lines=lines,
            start_line=chunk_start,
            end_line=chunk_end,
            symbol=None,
            kind="module",
        )
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def _symbol_chunks(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    *,
    relative_path: str,
    lines: list[str],
    max_lines: int,
    prefix: str = "",
) -> list[CodeChunk]:
    start_line = _node_start(node)
    end_line = node.end_lineno or node.lineno
    symbol = f"{prefix}.{node.name}" if prefix else node.name
    kind: ChunkKind = "class" if isinstance(node, ast.ClassDef) else "function"

    if not isinstance(node, ast.ClassDef) or end_line - start_line + 1 <= max_lines:
        chunk = _make_chunk(
            relative_path=relative_path,
            lines=lines,
            start_line=start_line,
            end_line=end_line,
            symbol=symbol,
            kind=kind,
        )
        return [chunk] if chunk is not None else []

    children = [item for item in node.body if isinstance(item, SYMBOL_NODES)]
    if not children:
        chunk = _make_chunk(
            relative_path=relative_path,
            lines=lines,
            start_line=start_line,
            end_line=end_line,
            symbol=symbol,
            kind="class",
        )
        return [chunk] if chunk is not None else []

    chunks: list[CodeChunk] = []
    cursor = start_line
    for child in children:
        child_start = _node_start(child)
        if cursor < child_start:
            class_context = _make_chunk(
                relative_path=relative_path,
                lines=lines,
                start_line=cursor,
                end_line=child_start - 1,
                symbol=symbol,
                kind="class",
            )
            if class_context is not None:
                chunks.append(class_context)
        chunks.extend(
            _symbol_chunks(
                child,
                relative_path=relative_path,
                lines=lines,
                max_lines=max_lines,
                prefix=symbol,
            )
        )
        cursor = (child.end_lineno or child.lineno) + 1
    if cursor <= end_line:
        class_context = _make_chunk(
            relative_path=relative_path,
            lines=lines,
            start_line=cursor,
            end_line=end_line,
            symbol=symbol,
            kind="class",
        )
        if class_context is not None:
            chunks.append(class_context)
    return chunks


def chunk_python_file(
    path: Path,
    *,
    root: Path,
    max_lines: int = 200,
) -> list[CodeChunk]:
    """按顶层函数/类切块；无法解析时退化为固定行数切块。"""
    if max_lines < 1:
        raise ValueError("max_lines 必须大于 0")
    source = path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    if not lines:
        return []
    relative_path = path.resolve().relative_to(root.resolve()).as_posix()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _line_chunks(
            relative_path=relative_path,
            lines=lines,
            start_line=1,
            end_line=len(lines),
            max_lines=max_lines,
        )

    symbols = [item for item in tree.body if isinstance(item, SYMBOL_NODES)]
    if not symbols:
        return _line_chunks(
            relative_path=relative_path,
            lines=lines,
            start_line=1,
            end_line=len(lines),
            max_lines=max_lines,
        )

    chunks: list[CodeChunk] = []
    cursor = 1
    for node in symbols:
        node_start = _node_start(node)
        if cursor < node_start:
            chunks.extend(
                _line_chunks(
                    relative_path=relative_path,
                    lines=lines,
                    start_line=cursor,
                    end_line=node_start - 1,
                    max_lines=max_lines,
                )
            )
        chunks.extend(
            _symbol_chunks(
                node,
                relative_path=relative_path,
                lines=lines,
                max_lines=max_lines,
            )
        )
        cursor = (node.end_lineno or node.lineno) + 1

    if cursor <= len(lines):
        chunks.extend(
            _line_chunks(
                relative_path=relative_path,
                lines=lines,
                start_line=cursor,
                end_line=len(lines),
                max_lines=max_lines,
            )
        )
    return chunks


async def build_index(
    root: Path,
    embedder: Embedder,
    *,
    max_lines: int = 200,
) -> CodeIndex:
    """切分仓库代码、批量生成向量并返回内存索引。"""
    root = root.resolve()
    files = discover_python_files(root)
    chunks = [
        chunk
        for path in files
        for chunk in chunk_python_file(path, root=root, max_lines=max_lines)
    ]
    if not chunks:
        raise ValueError(f"目录中没有可索引的 Python 代码: {root}")

    vectors = await embedder.embed(
        [chunk.embedding_text() for chunk in chunks]
    )
    if len(vectors) != len(chunks):
        raise RuntimeError("embedding 数量与代码块数量不一致")
    dimension = len(vectors[0])

    return CodeIndex(
        root=str(root),
        embedding_model=embedder.model,
        dimension=dimension,
        file_count=len(files),
        chunks=[
            IndexedChunk(**chunk.model_dump(), embedding=vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
    )


def save_index(index: CodeIndex, path: Path) -> Path:
    """先写临时文件，再原子替换正式索引。"""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary_path.write_text(
            index.model_dump_json(indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return path


def load_index(path: Path) -> CodeIndex:
    """读取并校验已持久化的向量索引。"""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"RAG 索引不存在: {path}")
    return CodeIndex.model_validate_json(path.read_text(encoding="utf-8"))
