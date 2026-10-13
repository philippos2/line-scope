"""Deterministic v1 UTF-8 plain-text chunks; no LLM or vector-store input.

The version names the algorithm and size. Other formats require an explicit
parser/version, not a silent fallback. Sections are source character ranges,
not invented document headings. No whitespace/Unicode normalization is applied.
"""

from dataclasses import dataclass, field
from uuid import UUID, uuid5

CHUNKING_VERSION = "utf8-fixed-1000:v1"
CHUNK_NAMESPACE = UUID("5bcf31ae-5aaa-46dd-b3ab-63a2b16a0d20")
CHUNK_CHARACTERS = 1000


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: UUID
    section: str
    text: str = field(repr=False)


def source_chunks(document_id: UUID, document_version: int, body: bytes):
    text = body.decode("utf-8", errors="strict")
    return tuple(
        KnowledgeChunk(
            uuid5(
                CHUNK_NAMESPACE, f"{document_id}:{document_version}:{ordinal}:{CHUNKING_VERSION}"
            ),
            f"characters:{start}-{min(start + CHUNK_CHARACTERS, len(text))}",
            text[start : start + CHUNK_CHARACTERS],
        )
        for ordinal, start in enumerate(range(0, len(text), CHUNK_CHARACTERS))
    )
