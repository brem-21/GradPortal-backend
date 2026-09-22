"""Split a document into embedding-sized pieces.

Splits on paragraph boundaries first and only falls back to sentence and then
hard token cuts, because an SOP paragraph carries an argument that loses its
meaning when cut in half — and a half-argument retrieves badly.
"""

import re
from dataclasses import dataclass

import tiktoken

_encoder = tiktoken.get_encoding("cl100k_base")

SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")

# Lines that look like CV or SOP section headings, used to label a chunk so the
# citation can say "from the Education section" rather than "chunk 7".
HEADING = re.compile(
    r"^\s*(?:[A-Z][A-Z \t&/-]{3,60}|"
    r"(?:Education|Experience|Employment|Skills|Publications|Projects|Awards|"
    r"Honours|Honors|References|Research|Objective|Summary|Profile|"
    r"Certifications|Languages|Interests|Teaching|Grants)\b.{0,40})\s*:?\s*$",
    re.MULTILINE,
)


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int
    page_number: int | None = None
    section: str | None = None


def count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


def _tail(text: str, overlap_tokens: int) -> str:
    if overlap_tokens <= 0:
        return ""
    return _encoder.decode(_encoder.encode(text)[-overlap_tokens:]).strip()


def _split_oversized(text: str, max_tokens: int, overlap_tokens: int = 0) -> list[str]:
    """A single paragraph longer than the window: try sentences, then hard cuts.

    Overlap applies here too. A dense CV block or an unbroken SOP paragraph is
    exactly where a claim straddles the boundary, so dropping the overlap on
    this path would lose context precisely where it matters most.
    """
    sentences = SENTENCE_BOUNDARY.split(text)
    pieces: list[str] = []
    buffer = ""

    def push(piece: str) -> None:
        piece = piece.strip()
        if piece:
            pieces.append(piece)

    for sentence in sentences:
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if count_tokens(candidate) <= max_tokens:
            buffer = candidate
            continue
        if buffer:
            push(buffer)
        if count_tokens(sentence) <= max_tokens:
            carry = _tail(pieces[-1], overlap_tokens) if pieces else ""
            buffer = f"{carry} {sentence}".strip() if carry else sentence
        else:
            # One sentence still too long (a dense table row, usually).
            tokens = _encoder.encode(sentence)
            step = max(1, max_tokens - overlap_tokens)
            for start in range(0, len(tokens), step):
                push(_encoder.decode(tokens[start : start + max_tokens]))
            buffer = ""
    if buffer:
        push(buffer)
    return pieces


def _page_for_offset(offset: int, page_offsets: list[int]) -> int | None:
    if not page_offsets:
        return None
    page = 1
    for index, start in enumerate(page_offsets):
        if offset >= start:
            page = index + 1
        else:
            break
    return page


def _section_at(offset: int, headings: list[tuple[int, str]]) -> str | None:
    current = None
    for position, label in headings:
        if position <= offset:
            current = label
        else:
            break
    return current


def chunk_document(
    text: str,
    *,
    max_tokens: int = 800,
    overlap_tokens: int = 120,
    page_offsets: list[int] | None = None,
    max_chunks: int = 400,
) -> list[Chunk]:
    text = text.strip()
    if not text:
        return []

    headings = [
        (match.start(), match.group(0).strip().rstrip(":")) for match in HEADING.finditer(text)
    ]

    # Walk paragraphs, tracking the character offset so page and section survive.
    paragraphs: list[tuple[int, str]] = []
    cursor = 0
    for block in text.split("\n\n"):
        stripped = block.strip()
        position = text.find(block, cursor)
        if position == -1:
            position = cursor
        cursor = position + len(block)
        if stripped:
            paragraphs.append((position, stripped))

    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_tokens = 0
    buffer_offset: int | None = None

    def flush() -> None:
        nonlocal buffer, buffer_tokens, buffer_offset
        if not buffer:
            return
        content = "\n\n".join(buffer).strip()
        if content:
            offset = buffer_offset or 0
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=content,
                    token_count=count_tokens(content),
                    page_number=_page_for_offset(offset, page_offsets or []),
                    section=_section_at(offset, headings),
                )
            )
        buffer = []
        buffer_tokens = 0
        buffer_offset = None

    for offset, paragraph in paragraphs:
        if len(chunks) >= max_chunks:
            break
        tokens = count_tokens(paragraph)

        if tokens > max_tokens:
            flush()
            for piece in _split_oversized(paragraph, max_tokens, overlap_tokens):
                if len(chunks) >= max_chunks:
                    break
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        content=piece,
                        token_count=count_tokens(piece),
                        page_number=_page_for_offset(offset, page_offsets or []),
                        section=_section_at(offset, headings),
                    )
                )
            continue

        if buffer_tokens + tokens > max_tokens and buffer:
            flush()
            # Carry the tail of the previous chunk forward so a point split
            # across the boundary is still retrievable from both sides.
            if overlap_tokens > 0 and chunks:
                tail_tokens = _encoder.encode(chunks[-1].content)[-overlap_tokens:]
                tail = _encoder.decode(tail_tokens).strip()
                if tail:
                    buffer.append(tail)
                    buffer_tokens = len(tail_tokens)

        if buffer_offset is None:
            buffer_offset = offset
        buffer.append(paragraph)
        buffer_tokens += tokens

    flush()
    for position, chunk in enumerate(chunks):
        chunk.index = position
    return chunks[:max_chunks]
