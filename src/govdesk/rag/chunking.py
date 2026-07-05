# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Strukturbewusstes Chunking mit harten Grenzen an Gesetzes-Paragraphen.

Token werden über eine Zeichen-Heuristik geschätzt (~4 Zeichen/Token) —
bewusst ohne Laden externer Tokenizer, damit auch Air-Gap-Betrieb ohne
HuggingFace-Downloads funktioniert. Für bge-m3-Fenster (8k) ist die
Genauigkeit mehr als ausreichend.
"""

import re
from dataclasses import dataclass, field

from govdesk.documents.parsers.base import Block

CHUNK_TOKENS = 450
OVERLAP_TOKENS = 60
CHARS_PER_TOKEN = 4

# Deutsche Rechtstexte: neue §§/Artikel beginnen immer einen neuen Chunk,
# damit Zitate wie „§ 3 VgV" nie zwei Paragraphen vermischen.
SECTION_BOUNDARY = re.compile(
    r"^\s*(§+\s?\d+[a-z]?|Art(?:ikel|\.)?\s?\d+[a-z]?|Anlage\s?\d*|Präambel)\b",
    re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class Chunk:
    text: str
    heading_path: str | None
    page_no: int | None
    token_count: int = 0

    def __post_init__(self) -> None:
        self.token_count = estimate_tokens(self.text)


@dataclass
class _Section:
    heading_path: str | None
    page_no: int | None
    paragraphs: list[str] = field(default_factory=list)


def _split_sections(blocks: list[Block]) -> list[_Section]:
    """Gruppiert Blöcke unter ihrem Überschriften-Pfad; §-Zeilen erzwingen Schnitte."""
    sections: list[_Section] = []
    heading_stack: list[tuple[int, str]] = []
    current: _Section | None = None

    def heading_path() -> str | None:
        return " > ".join(h for _, h in heading_stack) or None

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.heading_level is not None:
            heading_stack[:] = [h for h in heading_stack if h[0] < block.heading_level]
            heading_stack.append((block.heading_level, text))
            current = None
            continue
        if SECTION_BOUNDARY.match(text) or current is None:
            current = _Section(heading_path=heading_path(), page_no=block.page_no)
            if SECTION_BOUNDARY.match(text):
                marker = text.splitlines()[0].strip()
                base = current.heading_path
                current.heading_path = f"{base} > {marker}" if base else marker
            sections.append(current)
        current.paragraphs.append(text)
    return sections


def _split_oversized(paragraph: str, max_chars: int) -> list[str]:
    """Überlange Absätze an Satzgrenzen teilen."""
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    parts: list[str] = []
    buffer = ""
    for sentence in sentences:
        while len(sentence) > max_chars:  # Monster-Satz: hart schneiden
            parts.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if buffer and len(buffer) + len(sentence) + 1 > max_chars:
            parts.append(buffer)
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer:
        parts.append(buffer)
    return parts


def chunk_blocks(
    blocks: list[Block],
    chunk_tokens: int = CHUNK_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[Chunk]:
    max_chars = chunk_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    chunks: list[Chunk] = []

    for section in _split_sections(blocks):
        paragraphs = [
            part
            for paragraph in section.paragraphs
            for part in _split_oversized(paragraph, max_chars)
        ]
        window: list[str] = []
        window_len = 0
        for paragraph in paragraphs:
            if window and window_len + len(paragraph) + 2 > max_chars:
                chunks.append(Chunk("\n\n".join(window), section.heading_path, section.page_no))
                # Überlappung: letzte Absätze bis overlap_chars mitnehmen
                keep: list[str] = []
                kept = 0
                for prev in reversed(window):
                    if kept + len(prev) > overlap_chars:
                        break
                    keep.insert(0, prev)
                    kept += len(prev)
                window = keep
                window_len = kept
            window.append(paragraph)
            window_len += len(paragraph) + 2
        if window:
            chunks.append(Chunk("\n\n".join(window), section.heading_path, section.page_no))

    return chunks
