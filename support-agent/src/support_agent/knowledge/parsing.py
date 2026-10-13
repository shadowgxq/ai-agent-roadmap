"""Structure-first text parsing; PDF OCR is deliberately outside W19 P0."""

from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
import re

from .models import ChunkDraft


@dataclass
class Section:
    text: str
    heading_path: list[str] = field(default_factory=list)
    page: int | None = None


def parse_markdown(text: str) -> list[Section]:
    sections: list[Section] = []
    headings: list[tuple[int, str]] = []
    body: list[str] = []
    fence: str | None = None

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            sections.append(Section(content, [name for _, name in headings]))
        body.clear()

    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            body.append(line)
            continue
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line) if fence is None else None
        if heading:
            flush()
            level = len(heading[1])
            headings = [(depth, name) for depth, name in headings if depth < level]
            headings.append((level, heading[2]))
        else:
            body.append(line)
    flush()
    return sections


def parse_source(content: bytes, suffix: str) -> list[Section]:
    suffix = suffix.lower()
    if suffix in {".md", ".markdown"}:
        return parse_markdown(content.decode("utf-8-sig"))
    if suffix in {".txt", ".text"}:
        return [Section(content.decode("utf-8-sig").strip())]
    if suffix != ".pdf":
        raise ValueError("Supported sources: Markdown, UTF-8 text and text-layer PDF")
    from pypdf import PdfReader

    pages = [(page.extract_text() or "").splitlines() for page in PdfReader(BytesIO(content)).pages]
    if not any(any(line.strip() for line in page) for page in pages):
        raise ValueError("PDF has no text layer; OCR is not supported")
    # Only repeated lines at page edges qualify as headers/footers.
    edge_counts = Counter(
        line for page in pages for line in set(
            re.sub(r"\d+", "#", line.strip()) for line in page[:2] + page[-2:] if line.strip()
        )
    )
    repeated = {line for line, count in edge_counts.items()
                if len(pages) >= 3 and count >= max(3, (len(pages) + 1) // 2)}
    result = []
    for number, lines in enumerate(pages, 1):
        kept = [line for index, line in enumerate(lines)
                if not ((index < 2 or index >= len(lines) - 2)
                        and re.sub(r"\d+", "#", line.strip()) in repeated)]
        text = "\n".join(kept).strip()
        if text:
            result.append(Section(text, page=number))
    if not result:
        raise ValueError("PDF contains no body text after header/footer cleanup")
    return result


def _units(text: str) -> list[str]:
    """Keep fenced code and each list item intact before considering token limits."""
    units: list[str] = []
    current: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                if current:
                    units.append("\n".join(current).strip())
                current = [line]
                fence = marker[1]
                continue
            current.append(line)
            if marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                units.append("\n".join(current))
                current, fence = [], None
            continue
        if fence is not None:
            current.append(line)
            continue
        is_list = re.match(r"^\s*(?:[-+*]|\d+[.)])\s+", line)
        if not line.strip() or is_list:
            if current:
                units.append("\n".join(current).strip())
                current = []
        if line.strip():
            current.append(line)
    if current:
        units.append("\n".join(current).strip())
    return [unit for unit in units if unit]


def chunk_sections(sections: list[Section], *, max_tokens: int = 400,
                   overlap_tokens: int = 40) -> list[ChunkDraft]:
    import tiktoken

    if max_tokens < 16 or not 0 <= overlap_tokens < max_tokens:
        raise ValueError("Require max_tokens >= 16 and 0 <= overlap_tokens < max_tokens")
    encoding = tiktoken.get_encoding("cl100k_base")

    def tokens(text: str) -> int:
        return len(encoding.encode(text, disallowed_special=()))

    chunks: list[ChunkDraft] = []
    for section in sections:
        prefix = " / ".join(section.heading_path)
        prefix = prefix + "\n\n" if prefix else ""
        budget = max_tokens - tokens(prefix)
        if budget < 8:
            raise ValueError("Heading path exceeds chunk token budget; increase max_tokens")
        parts: list[str] = []

        def emit() -> None:
            if parts:
                chunks.append(ChunkDraft(text=prefix + "\n\n".join(parts),
                                         heading_path=section.heading_path, page=section.page))

        for unit in _units(section.text):
            if tokens(unit) > budget:
                emit()
                parts = []
                # Slice on Unicode character boundaries so byte-split tokens cannot corrupt text.
                start = 0
                while start < len(unit):
                    low, high = start + 1, len(unit)
                    end = low
                    while low <= high:
                        middle = (low + high) // 2
                        if tokens(unit[start:middle]) <= budget:
                            end, low = middle, middle + 1
                        else:
                            high = middle - 1
                    chunks.append(ChunkDraft(text=prefix + unit[start:end],
                                             heading_path=section.heading_path, page=section.page))
                    if end == len(unit):
                        break
                    next_start = end
                    while next_start > start + 1 and tokens(unit[next_start - 1:end]) <= min(overlap_tokens, budget // 4):
                        next_start -= 1
                    start = next_start
                continue
            candidate = "\n\n".join(parts + [unit])
            if tokens(candidate) > budget:
                emit()
                # Overlap whole units only when small enough; never exceed the token budget.
                tail = parts[-1:] if parts and tokens(parts[-1]) <= overlap_tokens else []
                parts = tail if tokens("\n\n".join(tail + [unit])) <= budget else []
            parts.append(unit)
        emit()
    return chunks
